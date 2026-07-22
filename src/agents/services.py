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


def generate_exercise(
    text: str, skill_types: Literal["reading", "speaking", "listening", "writing"]
):
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


def skill_type_classification(
    text: str,  # prompt user atau pesan-nya
):
    """Menentukan kebutuhan latihan yang tepat berdasarkan pesan yang disampaikan oleh peserta"""

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

    data = EvaluateUserIntentionSchema.model_validate(json.load(response.text))
    # data.skill_types # reading, listening, speaking atau writing

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
