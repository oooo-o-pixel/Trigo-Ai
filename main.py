from  fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(
    title="Trigo-Ai",
    description="AI Football Companion with WalMemory",
    version="1.0.0",
)

#Request and Response Models

class ChatRequest(BaseModel):
    wallet_address: str
    message: str

class ChatResponse(BaseModel):
    success: bool
    reply: str

# Root route
@app.get("/")
def home():
    return {
        "success": True,
        "message": "Welcome to Trigo-Ai API!"
    }

# health check route
@app.get("/health")
def health_check():
    return {
        "success": True,
        "status": "API is healthy and running!"
    }

# Chat route
@app.post("/chat", response_model=ChatResponse)
def chat(chat_request: ChatRequest):
    user_message = chat_request.message.lower()

    # Temporary block data for demonstration
    if "portugal" in user_message:
        reply = "Portugal is a great football team with a rich history. They have won the UEFA European Championship in 2016 and have produced legendary players like Cristiano Ronaldo."
    elif "world cup" in user_message:
        reply = "The FIFA World Cup is the most prestigious football tournament in the world, held every four years. The next World Cup will be in 2026, hosted by the USA, Canada, and Mexico."
    else:
        reply = "I'm here to help with any football-related questions you have! Ask me about teams, players, tournaments, or anything else football-related."
    # Here you would typically process the block data, interact with your AI model, and generate a response.
    # For demonstration purposes, we'll just return the received data.
    
    return ChatResponse(
        success=True,
        reply=reply
    )