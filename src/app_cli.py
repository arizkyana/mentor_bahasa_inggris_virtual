from src.agents.lead import LeadAgent
from loguru import logger

lead_agent = LeadAgent()


def init():
    print(
        "Mentor Bahasa Inggris Virtual \n"
        "Coba tulis pesan: \n"
        "- buatkan soal reading \n"
        "- periksa tulisan: `I goes to school` \n"
        "- kasih tips belajar \n"
        "atau ngobrol bebas"
    )

    while True:
        prompt = input("[user]: ")

        if prompt.lower() == "/exit":
            break

        response = lead_agent.handle_send_message(
            user_id=100918936, message_text=prompt
        )

        logger.success(f"[AI]: {response["text"]}")
