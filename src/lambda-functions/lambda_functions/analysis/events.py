from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    appid: int
    game_name: str = ""
