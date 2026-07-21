import src.core.env as env
import src.core.llm as llm
import src.agents.services as services  # akan kita lengkapi pada materi berikutnya
import src.core.prompts as prompts
import src.core.artifacts as artifacts


from google.genai import types

from src.repository.chat_repository import ChatRepository


class LeadAgent:
    def __init__(self):
        # gemini
        self.client = llm.get_gemini_client()

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

    # pythonic way: nama function dengan awalan _ akan dipanggil secara private
    def _load_history(self, user_id: int):
        """Mengambil history chart dari supabase kemudian diubah ke format Gemini"""

        response = self.chat_repository.load_history_by_user_id(user_id=user_id)
        # list comprehension

        return [
            types.Content(
                role=row["role"], parts=[types.Part(text=row["message_text"])]
            )
            for row in response.data
        ]

    def handle_send_message(self, user_id: int, message_text: str):
        """Menjawab pesan user memakai automatic function calling (AFC).

        Tools didaftarkaan sebagai function Python biasa. SDK google-genai yang mendeteksi
        function call, menjalankan fungsinya, mengirim hasil balik ke model dan mengembalikan
        teks final. Setiap tool sudah mencatat error sendiri lewat `logger.exception` agar tetap terlihat
        di log.

        Mengembalikan dict `{"text": ... "artifacts": [...]}`. `artifacts` berisi file (contoh: audio listening)
        yang dicatat tool lewat `src.core.artifacts` dan harus dikirim terpisah oleh layer pengiriman (CLI/Telegram)
        """

        self.chat_repository.save_message(
            role="user", user_id=user_id, message_text=message_text
        )

        contents = self._load_history(user_id=user_id)

        # siapkan keranjang artifact untuk request ini
        artifacts.start()

        response = self.client.models.generate_content(
            model=env.GEMINI_MODEL,
            config=types.GenerateContentConfig(
                system_instruction=self.lead_agent_instruction,
                tools=self.tools,
            ),
            contents=contents,
        )

        answer = response.text
        artifacts_data = artifacts.collect()

        # handle artifacts
        for item in artifacts_data:
            self.chat_repository.save_artifact(
                user_id=user_id, artifact_path=item["path"]
            )

        self.chat_repository.save_message(
            role="model", user_id=user_id, message_text=answer
        )

        collected_artifacts = (
            self.chat_repository.get_last_artifact_by_user_id(user_id=user_id)
            if artifacts_data
            else []
        )

        return {"text": answer, "artifacts": collected_artifacts}

    def handle_send_voice(self, user_id: int, voice_file_path: str):
        self.chat_repository.save_message(
            user_id=user_id, role="user", message_text="[voice note]"
        )

        evaluation_speaking_result = services.evaluate_speaking(
            voice_file_path=voice_file_path
        )

        self.chat_repository.save_message(
            user_id=user_id, role="model", message_text=evaluation_speaking_result
        )

        return evaluation_speaking_result

    def handle_report(
        self, user_id: int, username: str, start_date: str, end_date: str
    ):
        self.chat_repository.save_message(
            user_id=user_id,
            role="user",
            message_text=f"[generate learning report: {start_date} - {end_date}]",
        )

        history = self._load_history(user_id=user_id)

        report_file_path = services.generate_report(
            conversation_history=history,
            start_date=start_date,
            end_date=end_date,
            username=username,
        )

        self.chat_repository.save_message(
            user_id=user_id,
            role="model",
            message_text=f"[generate learning report: {start_date} - {end_date} sudah selesai dicetak]",
        )

        return report_file_path
