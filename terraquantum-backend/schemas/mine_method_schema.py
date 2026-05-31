from pydantic import BaseModel


class MineMethodRequest(BaseModel):
    project_id: str
    run_id: str
