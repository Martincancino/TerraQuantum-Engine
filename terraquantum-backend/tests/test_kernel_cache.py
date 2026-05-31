"""
Track 3 / T3.3 — Caché de G_active (memoización de geometría en el forward model).

El kernel depende SOLO de la geometría (coords activas, sensores, dx/dy/dz, cutoff),
no de λ/m_ref/ruido. Dentro de un run, solve/L-curve/DOI/UQ reusan la misma geometría
→ se evita reconstruir el KDTree. Estas pruebas garantizan que la caché NO altera el
resultado (bit-idéntico a una construcción fresca) y que detecta cambios de geometría.
"""
import numpy as np

from exploration.gravimetry import GravimetryForward


def _grid(nx=6, ny=4, nz=6, block=10.0):
    gx, gy, gz = np.mgrid[0:nx, 0:ny, 0:nz]
    x = (gx.flatten(order="F") * block + block / 2).astype(float)
    y = (gy.flatten(order="F") * block + block / 2).astype(float)
    z = (gz.flatten(order="F") * block + block / 2).astype(float)
    sensors = np.array([[15, 0, 15], [25, 0, 15], [35, 0, 25], [45, 0, 35]], dtype=float)
    return x, y, z, sensors


def _equal_csr(a, b):
    a = a.tocsr(); b = b.tocsr()
    return (
        a.shape == b.shape
        and np.array_equal(a.indptr, b.indptr)
        and np.array_equal(a.indices, b.indices)
        and np.array_equal(a.data, b.data)
    )


def test_cache_hit_skips_rebuild_same_object():
    fwd = GravimetryForward(10, 10, 10, cutoff_radius=400.0)
    x, y, z, s = _grid()
    k1 = fwd._build_sparse_kernel(x, y, z, s)
    assert fwd.kernel_build_count == 1
    k2 = fwd._build_sparse_kernel(x, y, z, s)   # misma geometría → HIT
    assert fwd.kernel_build_count == 1, "un hit no debe reconstruir"
    assert k2 is k1, "el hit debe devolver la matriz cacheada"


def test_cache_miss_on_changed_geometry():
    fwd = GravimetryForward(10, 10, 10, cutoff_radius=400.0)
    x, y, z, s = _grid()
    fwd._build_sparse_kernel(x, y, z, s)                 # build 1
    s2 = s + np.array([5.0, 0.0, 5.0])                   # sensores distintos
    fwd._build_sparse_kernel(x, y, z, s2)                # build 2 (miss)
    assert fwd.kernel_build_count == 2


def test_cache_bit_identical_to_fresh_build():
    """Garantía de corrección: la matriz cacheada es idéntica a una fresca."""
    fwd = GravimetryForward(10, 10, 10, cutoff_radius=400.0)
    x, y, z, s = _grid()
    k_cached = fwd._build_sparse_kernel(x, y, z, s)
    # Forzar reconstrucción fresca (limpiar caché).
    fwd._kernel_cache = None
    fwd._kernel_cache_mat = None
    k_fresh = fwd._build_sparse_kernel(x, y, z, s)
    assert _equal_csr(k_cached, k_fresh), "caché y construcción fresca deben coincidir bit a bit"


def test_cache_distinguishes_coords_with_same_shape():
    """Geometría con misma FORMA pero coords distintas no debe colisionar (array_equal)."""
    fwd = GravimetryForward(10, 10, 10, cutoff_radius=400.0)
    x, y, z, s = _grid()
    k1 = fwd._build_sparse_kernel(x, y, z, s)
    x2 = x.copy(); x2[0] += 3.0                          # misma forma, un valor distinto
    k2 = fwd._build_sparse_kernel(x2, y, z, s)
    assert fwd.kernel_build_count == 2                   # debió reconstruir
    assert not _equal_csr(k1, k2)


def test_cache_does_not_corrupt_after_caller_mutation():
    """Las claves se guardan como copias: mutar el array del caller no envenena la caché."""
    fwd = GravimetryForward(10, 10, 10, cutoff_radius=400.0)
    x, y, z, s = _grid()
    fwd._build_sparse_kernel(x, y, z, s)
    x[:] += 1000.0                                        # caller muta su array después
    # Nueva llamada con la geometría ORIGINAL debe seguir dando HIT correcto.
    x_orig = x - 1000.0
    k = fwd._build_sparse_kernel(x_orig, y, z, s)
    assert fwd.kernel_build_count == 1, "la clave copiada protege el hit"
    assert k is fwd._kernel_cache_mat
