"""Central factory for LLM (Emergent proxy) + local HuggingFace embeddings."""
import os
from functools import lru_cache
from openai import OpenAI
from langchain_openai import ChatOpenAI
from langchain_community.embeddings import HuggingFaceEmbeddings
from sentence_transformers import SentenceTransformer

EMERGENT_KEY = os.environ["EMERGENT_LLM_KEY"]
BASE_URL = os.environ["OPENAI_API_BASE"]
LLM_MODEL = os.environ["LLM_MODEL"]
EMBED_MODEL = os.environ["EMBED_MODEL"]   # e.g. sentence-transformers/all-MiniLM-L6-v2
EMBED_DIM = int(os.environ["EMBED_DIM"])  # e.g. 384 for MiniLM


@lru_cache(maxsize=1)
def get_openai() -> OpenAI:
    return OpenAI(api_key=EMERGENT_KEY, base_url=BASE_URL)


@lru_cache(maxsize=1)
def get_chat_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=LLM_MODEL,
        api_key=EMERGENT_KEY,
        base_url=BASE_URL,
        temperature=0,
    )


@lru_cache(maxsize=1)
def _st_model() -> SentenceTransformer:
    return SentenceTransformer(EMBED_MODEL)


@lru_cache(maxsize=1)
def get_embeddings() -> HuggingFaceEmbeddings:
    # LangChain wrapper used by RAGAS
    return HuggingFaceEmbeddings(model_name=EMBED_MODEL)


def embed_text(text: str) -> list[float]:
    v = _st_model().encode([text], normalize_embeddings=True)[0]
    return v.tolist()


def embed_texts(texts: list[str]) -> list[list[float]]:
    v = _st_model().encode(list(texts), normalize_embeddings=True, batch_size=32)
    return [row.tolist() for row in v]
