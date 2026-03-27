from fastapi import FastAPI
import os
from supabase import create_client, Client

url: str = os.environ.get("SUPABASE_URL") # type: ignore
key: str = os.environ.get("SUPABASE_KEY") # type: ignore
supabase: Client = create_client(url, key)

app = FastAPI()


@app.get("/")
async def get_hello():
    return {"message": "nomad v0.0.1 beta"}

@app.post("/posts")
def post(authorId:str, content:str, communityId:str, description:str):
    pass