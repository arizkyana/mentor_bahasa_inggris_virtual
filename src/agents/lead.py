import src.core.env as env
import src.core.llm as llm
import src.agents.services as services  # kita akan melengkapi pada materi berikutnya
import src.core.prompts as prompts
import src.core.artifacts as artifacts

from src.repository.chat_repository import ChatRepository
from google.genai import types
from loguru import logger

MAX_HISTORY_ITEMS = 10


class LeadAgent:
    def __init__(self, user_id):
        # set user_id di sini, untuk memastikan satu objeck LeadAgent hanya untuk satu user telegram saja
        self.user_id = user_id
        # gemini
        self.gemini_client = llm.get_gemini_client()

        # agents
        self.tools = [
            services.skill_type_classification,
            services.evaluate_writing,
            services.get_learning_tip,
        ]

        # chat repository
        self.chat_repository = ChatRepository()

        # lead agent instruction
        self.lead_agent_instruction = prompts.load_instruction("agent-lead")

        self.chat_model = None

        self.history = []

    def _load_history(self, user_id: int):
        """Mengambil history chat dari supabase kemudian diubah ke format Gemini"""

        response = self.chat_repository.load_history_by_user_id(user_id=user_id)

        # list comprehension
        return [
            types.Content(
                role=row["role"], parts=[types.Part(text=row["message_text"])]
            )
            for row in response.data
        ]

    def start_or_resume(self, init_history=None):
        if init_history:
            self.history = init_history

        # pastikan ukuran history tidak lebih dari maksimal giliran percakapan

        if len(self.history) > MAX_HISTORY_ITEMS:
            # ambil sejumlah percakapan terakhir (paling baru) dari history
            # jumlah tergantung nilai konstanta MAX_HISTORY_ITEMS
            # pada contoh ini, akan di ambil 10 percakapan terakhir
            self.history = self.history[-(MAX_HISTORY_ITEMS):]

        self.chat_model = self.gemini_client.chats.create(
            model=env.GEMINI_MODEL,
            config=types.GenerateContentConfig(
                system_instruction=self.lead_agent_instruction, tools=self.tools
            ),
            history=self.history,
        )

    def handle_send_message(self, message_text: str):

        if not self.chat_model:
            self.start_or_resume(init_history=self._load_history(self.user_id))

        self.chat_repository.save_message(
            user_id=self.user_id, role="user", message_text=message_text
        )

        # siapkan keranjang artifact untuk setiap request
        artifacts.start()

        response_token_count = self.gemini_client.models.count_tokens(
            model=env.GEMINI_MODEL,
            contents=message_text,
        )

        logger.debug(f"total tokens: {response_token_count.total_tokens}")

        response = self.chat_model.send_message(message_text)

        answer = response.text
        artifacts_data = artifacts.collect()

        # handle artifact
        for item in artifacts_data:
            self.chat_repository.save_artifact(
                user_id=self.user_id, artifact_path=item["path"]
            )

        self.chat_repository.save_message(
            role="model", user_id=self.user_id, message_text=answer
        )

        # update history
        # pakai currated untuk mengambil history conversation yang valid -> lengkap struktur data Parts, Content dll
        self.history = self.chat_model.get_history(curated=True)

        return {"text": answer, "artifacts": artifacts_data}

    def handle_send_voice(self, voice_file_path: str):
        self.chat_repository.save_message(
            user_id=self.user_id, role="user", message_text="[voice note]"
        )

        evaluation_speaking_result = services.evaluate_speaking(
            voice_file_path=voice_file_path
        )

        self.chat_repository.save_message(
            user_id=self.user_id, role="model", message_text=evaluation_speaking_result
        )

        return evaluation_speaking_result

    def handle_report(self, username: str, start_date: str, end_date: str):
        self.chat_repository.save_message(
            user_id=self.user_id,
            role="user",
            message_text=f"[generate learning report: {start_date} - {end_date}]",
        )

        history = self._load_history(user_id=self.user_id)

        report_file_path = services.generate_report(
            conversation_history=history,
            start_date=start_date,
            end_date=end_date,
            username=username,
        )

        self.chat_repository.save_message(
            user_id=self.user_id,
            role="model",
            message_text=f"[generate learning report: {start_date} - {end_date} sudah selesai dicetak]",
        )

        return report_file_path


# jelaskan kegunaan dari variabel self.tool pada function handle_send_message?
