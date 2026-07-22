import random
import json
import wave
import time

import src.core.env as env
import src.core.llm as llm
import src.core.prompts as prompts
import src.core.artifacts as artifacts

from datetime import datetime
from pathlib import Path
from google.genai import types
from markdown_pdf import MarkdownPdf, Section
from typing import Literal
from loguru import logger

from src.core.schemas import (
    LearningReportSchema,
    ListeningExerciseSchema,
    EvaluateUserIntentionSchema,
)

gemini_client = llm.get_gemini_client()
timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def generate_exercise(
    text: str, skill_types: Literal["reading", "speaking", "listening", "writing"]
):
    logger.debug(f"[generate_exercise] {skill_types}")

    match skill_types:
        case "writing":
            return writing_exercise(text=text)
        case "speaking":
            return speaking_exercise(text=text)
        case "listening":
            return listening_exercise(text=text)
        case "reading":
            return reading_exercise(text=text)


def writing_exercise(text: str):
    model = env.GEMINI_MODEL
    system_instruction = prompts.load_instruction("agent-writing-exercise")
    prompt = (
        f"Buatkan latihan writing berdasarkan permintaan user berikut ini: \n {text}"
    )

    response = gemini_client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(system_instruction=system_instruction),
    )

    return response.text


def speaking_exercise(text: str):
    model = env.GEMINI_MODEL
    system_instruction = prompts.load_instruction("agent-speaking-exercise")
    prompt = (
        f"Buatkan latihan speaking berdasarkan permintaan user berikut ini: \n {text}"
    )

    response = gemini_client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(system_instruction=system_instruction),
    )

    return response.text


def reading_exercise(text: str):
    model = env.GEMINI_MODEL
    system_instruction = prompts.load_instruction("agent-reading-exercise")
    prompt = (
        f"Buatkan latihan reading berdasarkan permintaan user berikut ini: \n {text}"
    )

    response = gemini_client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(system_instruction=system_instruction),
    )

    return response.text


def _listening_generate_script(text: str):
    model = env.GEMINI_MODEL
    system_instruction = prompts.load_instruction("agent-generate-script")
    prompt = f"Buatkan 1 latihan listening berdasarkan permintaan peserta berikut ini: \n {text}"

    response = gemini_client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_json_schema=ListeningExerciseSchema.model_json_schema(),
        ),
    )

    data = ListeningExerciseSchema.model_validate(json.loads(response.text))

    return data


def _listening_generate_audio_script(generate_script: ListeningExerciseSchema):
    model = env.GEMINI_MODEL_TTS

    script = generate_script.script
    speaker_one = generate_script.speaker_one
    speaker_two = generate_script.speaker_two

    prompt = f"Buatkan audio (text-to-speech) dari percakapan antara dua orang pada script berikut ini: {script}"

    response = gemini_client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                    speaker_voice_configs=[
                        types.SpeakerVoiceConfig(
                            speaker=speaker_one,
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name="Puck"
                                )
                            ),
                        ),
                        types.SpeakerVoiceConfig(
                            speaker=speaker_two,
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name="Kore"
                                )
                            ),
                        ),
                    ]
                )
            ),
        ),
    )

    candidates = response.candidates or []
    for candidate in candidates:
        parts = candidate.content.parts if candidate.content else []
        for part in parts:
            if part.inline_data and part.inline_data.data:
                return part.inline_data.data


def _write_wave_file(
    filename: str | Path,
    pcm: bytes,
    channels: int = 1,
    rate: int = 24000,
    sample_width: int = 2,
):
    with wave.open(str(filename), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm)


def listening_exercise(text: str):
    env.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    audio_output_path = env.OUTPUT_DIR / f"listening-{timestamp}.wav"

    # 1. "model" untuk generate script percakapan dua orang
    generate_script = _listening_generate_script(text=text)

    # 2. model generate audio
    audio = _listening_generate_audio_script(generate_script=generate_script)

    # 3. generate wav file
    _write_wave_file(audio_output_path, audio)

    # 4. catat file audio ke channel artifact
    artifacts.add(
        path=audio_output_path,
        kind="audio",
        caption="🎧 dengarkan audio latihan listening ini, lalu jawab pertanyaannya.",
    )

    # 5. kembalikan daftar pertanyaan
    questions_text = "\n".join(
        f"- {question}" for question in generate_script.questions
    )

    return (
        "Audio latihan listening sudah dibuat dan dilampirkan otomatis."
        f"Pertanyaan: \n{questions_text}"
    )


def skill_type_classification(
    text: str,  # prompt user atau pesan-nya
):
    """Menentukan kebutuhan latihan yang tepat berdasarkan pesan yang disampaikan oleh peserta"""

    logger.debug(f"[skill_type_classification agent]")

    model = env.GEMINI_MODEL
    system_instruction = prompts.load_instruction("agent-skill-type-classifier")
    prompt = f"pelajari pesan yang disampaikan oleh peserta kemudian tentukan latihan `skill_type` yang tepat: \n {text}"

    response = gemini_client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_json_schema=EvaluateUserIntentionSchema.model_json_schema(),
            temperature=0.3,  # AI akan menjawab secara tegas
        ),
    )

    logger.debug(f"[response.text: {response.text}]")

    data = EvaluateUserIntentionSchema.model_validate(json.loads(response.text))
    # data.skill_types # reading, listening, speaking atau writing

    logger.debug(f"[skill_types: {data.skill_types}]")

    return generate_exercise(
        text=text,
        skill_types=data.skill_types,
    )


def evaluate_writing():
    return ""


def get_learning_tip():
    """Memberikan 1 tips berguna untuk belajar bahasa inggris"""

    tips = [
        "Latihan berbicara 10 menit sehari lebih efektif daripada belajar 2 jam seminggu sekali.",
        "Tonton film atau series berbahasa Inggris dengan subtitle bahasa Inggris, bukan Indonesia.",
        "Catat 5 kata baru setiap hari dan coba gunakan masing-masing dalam satu kalimat.",
        "Jangan takut salah — kesalahan adalah bagian dari proses belajar yang paling berharga.",
        "Coba berpikir dalam Bahasa Inggris saat melakukan aktivitas sehari-hari.",
    ]

    return random.choice(tips)


def evaluate_speaking():
    return ""


def generate_report():
    return ""
