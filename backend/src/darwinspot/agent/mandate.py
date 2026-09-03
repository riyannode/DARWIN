from pydantic import BaseModel, Field


class MandateInput(BaseModel):
    assets: str = Field(min_length=1, max_length=2000)
    entry_rules: str = Field(min_length=1, max_length=4000)
    sizing_rules: str = Field(min_length=1, max_length=2000)
    exit_rules: str = Field(min_length=1, max_length=4000)
