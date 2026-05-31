import numpy as np
import polars as pl
import heapq

class TruckPhysics:
    """
    Física de movimiento CAEX.
    Separa la evaluación determinística (para el Dispatch) de la simulación estocástica (para la realidad).
    """
    def __init__(self, model="CAT_797F", payload_t=360.0, tare_t=260.0, max_power_kw=2983.0):
        self.model = model
        self.payload_t = payload_t
        self.tare_t = tare_t
        self.max_power_kw = max_power_kw
        self.mech_efficiency = 0.85 
        self.rolling_resistance = 2.0 

    def _get_base_time_min(self, distance_km, gradient_pct, is_loaded):
        """Cálculo físico puro (Determinístico)"""
        weight_t = (self.payload_t + self.tare_t) if is_loaded else self.tare_t
        total_resistance = gradient_pct + self.rolling_resistance

        if total_resistance <= 0:
            v_kmh = 35.0 if is_loaded else 50.0
        else:
            force_newtons = (weight_t * 1000) * 9.81 * (total_resistance / 100.0)
            v_ms = (self.max_power_kw * 1000 * self.mech_efficiency) / force_newtons
            v_kmh = v_ms * 3.6
            
        max_safe_speed = 35.0 if is_loaded else 50.0
        v_kmh = min(v_kmh, max_safe_speed)

        return (distance_km / v_kmh) * 60.0

    def get_expected_travel_time(self, distance_km, gradient_pct, is_loaded):
        """Para el cerebro del Dispatch (Sin ruido)"""
        return self._get_base_time_min(distance_km, gradient_pct, is_loaded)

    def get_travel_time_min(self, distance_km, gradient_pct, is_loaded):
        """Para la simulación física (Con ruido estocástico)"""
        base_time_min = self._get_base_time_min(distance_km, gradient_pct, is_loaded)
        actual_time_min = np.random.normal(base_time_min, base_time_min * 0.05)
        return max(0.1, actual_time_min)


class Shovel:
    """Representa un equipo de carguío individual."""
    def __init__(self, shovel_id, node_id, load_time_mean=3.5, load_time_std=0.3):
        self.id = shovel_id
        self.node_id = node_id
        self.load_time_mean = load_time_mean
        self.load_time_std = load_time_std
        self.is_busy = False
        self.is_down = False
        self.queue = []  # Cola de prioridad (heapq)
        self.total_mined_t = 0.0


class DispatchEngineV2:
    """Cerebro FMS con optimización económica, Multi-Pala y Multi-Ruta."""
    def __init__(self, truck_physics: TruckPhysics):
        self.truck = truck_physics
        self.reset_network()

    def reset_network(self):
        """Limpieza total del estado operacional entre simulaciones anuales."""
        self.shovels = {}
        self.routes = {} 
        self.event_queue = []
        self.time_now = 0.0
        self.total_loads = 0
        self.total_wait_time_min = 0.0

    def add_shovel(self, shovel_id, node_id):
        self.shovels[shovel_id] = Shovel(shovel_id, node_id)

    def add_route(self, node_a, node_b, distance_km, gradient_pct):
        self.routes[(node_a, node_b)] = (distance_km, gradient_pct)
        self.routes[(node_b, node_a)] = (distance_km, -gradient_pct)

    def schedule_event(self, delay, event_type, *args):
        event_time = self.time_now + delay
        heapq.heappush(self.event_queue, (event_time, event_type, args))

    def _assign_best_shovel(self, current_node):
        """DISPATCH ECONÓMICO: Optimiza Valor vs Tiempo usando Tiempos Esperados."""
        best_shovel = None
        min_score = float('inf')
        
        # Parámetros económicos operacionales
        fuel_rate = 2.5   # USD por km base
        maint_rate = 1.2  # USD por minuto de operación

        for s_id, shovel in self.shovels.items():
            if shovel.is_down:
                continue 
                
            dist, grad = self.routes.get((current_node, shovel.node_id), (1.0, 0.0))
            
            # 🔥 USAMOS EXPECTED TIME (Sin ruido) 🔥
            est_travel = self.truck.get_expected_travel_time(dist, grad, is_loaded=False)
            
            est_queue = len(shovel.queue) * shovel.load_time_mean
            if shovel.is_busy:
                est_queue += (shovel.load_time_mean / 2.0) 
                
            # 🔥 MODELO DE COSTO REALISTA 🔥
            # El consumo de diésel se dispara con la pendiente
            fuel_cost = dist * (1.0 + (abs(grad) / 10.0)) * fuel_rate
            maintenance_cost = est_travel * maint_rate
            
            # SCORE: Se busca el mínimo "castigo" global
            score = est_travel + est_queue + fuel_cost + maintenance_cost
            
            if score < min_score:
                min_score = score
                best_shovel = shovel

        return best_shovel

    def run_shift(self, fleet_size, dump_node="DUMP_MAIN", shift_hours=12.0):
        # El reset network ya fue llamado desde el scheduler antes de poblar las rutas
        
        arrival_times = {}

        for truck_id in range(fleet_size):
            stagger = np.random.uniform(0, 5.0)
            self.schedule_event(stagger, "TRUCK_READY", truck_id, dump_node)

        for s_id in self.shovels.keys():
            if np.random.random() < 0.30:
                fail_time = np.random.uniform(60.0, shift_hours * 60.0 * 0.8)
                self.schedule_event(fail_time, "SHOVEL_DOWN", s_id)

        max_time = shift_hours * 60.0
        
        while self.event_queue and self.time_now < max_time:
            self.time_now, event_type, args = heapq.heappop(self.event_queue)
            
            if self.time_now > max_time:
                break

            if event_type == "TRUCK_READY":
                truck_id, current_node = args
                target_shovel = self._assign_best_shovel(current_node)
                
                if target_shovel:
                    dist, grad = self.routes.get((current_node, target_shovel.node_id), (1.0, 0.0))
                    travel_empty = self.truck.get_travel_time_min(dist, grad, is_loaded=False)
                    self.schedule_event(travel_empty, "ARRIVE_SHOVEL", truck_id, target_shovel.id)
                else:
                    self.schedule_event(5.0, "TRUCK_READY", truck_id, current_node)

            elif event_type == "ARRIVE_SHOVEL":
                truck_id, s_id = args
                shovel = self.shovels[s_id]
                
                if shovel.is_busy or shovel.is_down:
                    heapq.heappush(shovel.queue, (self.time_now, truck_id))
                    arrival_times[truck_id] = self.time_now
                else:
                    shovel.is_busy = True
                    load_time = max(0.1, np.random.normal(shovel.load_time_mean, shovel.load_time_std))
                    self.schedule_event(load_time, "FINISH_LOADING", truck_id, s_id)

            elif event_type == "FINISH_LOADING":
                truck_id, s_id = args
                shovel = self.shovels[s_id]
                self.total_loads += 1
                shovel.total_mined_t += self.truck.payload_t
                
                dist, grad = self.routes.get((shovel.node_id, dump_node), (1.0, 0.0))
                travel_loaded = self.truck.get_travel_time_min(dist, grad, is_loaded=True)
                self.schedule_event(travel_loaded, "ARRIVE_DUMP", truck_id, dump_node)
                
                if shovel.queue and not shovel.is_down:
                    _, next_truck = heapq.heappop(shovel.queue)
                    wait_time = self.time_now - arrival_times[next_truck]
                    self.total_wait_time_min += wait_time
                    
                    load_time = max(0.1, np.random.normal(shovel.load_time_mean, shovel.load_time_std))
                    self.schedule_event(load_time, "FINISH_LOADING", next_truck, s_id)
                else:
                    shovel.is_busy = False

            elif event_type == "ARRIVE_DUMP":
                truck_id, dump_node_id = args
                dump_time = max(0.1, np.random.normal(1.2, 0.2))
                self.schedule_event(dump_time, "FINISH_DUMPING", truck_id, dump_node_id)

            elif event_type == "FINISH_DUMPING":
                truck_id, dump_node_id = args
                self.schedule_event(0.0, "TRUCK_READY", truck_id, dump_node_id)

            elif event_type == "SHOVEL_DOWN":
                s_id = args[0]
                shovel = self.shovels[s_id]
                shovel.is_down = True
                repair_time = np.random.uniform(60.0, 180.0)
                self.schedule_event(repair_time, "SHOVEL_REPAIRED", s_id)

            elif event_type == "SHOVEL_REPAIRED":
                s_id = args[0]
                shovel = self.shovels[s_id]
                shovel.is_down = False
                
                if shovel.queue:
                    _, next_truck = heapq.heappop(shovel.queue)
                    wait_time = self.time_now - arrival_times[next_truck]
                    self.total_wait_time_min += wait_time
                    shovel.is_busy = True
                    load_time = max(0.1, np.random.normal(shovel.load_time_mean, shovel.load_time_std))
                    self.schedule_event(load_time, "FINISH_LOADING", next_truck, s_id)

        # KPIs Industriales OEE
        total_nominal_tons = self.total_loads * self.truck.payload_t
        availability_ma = 0.85 
        utilization_ua = 0.75   
        
        real_tph = (total_nominal_tons / shift_hours) * availability_ma * utilization_ua
        return real_tph