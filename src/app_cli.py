from src.agents.lead import LeadAgent
from loguru import logger

lead_agent = LeadAgent()


def init():
    print("Mentor Bahasa Inggris Virtual")

    while True:
        prompt = input("[user]: ")

        if prompt.lower() == "/exit":
            break

        response = lead_agent.handle_send_message(user_id=1, message_text=prompt)

        logger.success(f"[AI]: {response["text"]}")
