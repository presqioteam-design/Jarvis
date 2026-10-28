from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..deps import require_user
from ..services import chat

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ChatOut(BaseModel):
    reply: str


@router.post("", response_model=ChatOut)
async def post_chat(body: ChatIn, _uid: str = Depends(require_user)) -> ChatOut:
    reply, _ = await chat.handle(body.message, channel="web")
    return ChatOut(reply=reply)
