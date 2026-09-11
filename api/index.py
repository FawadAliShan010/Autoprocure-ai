import sys
import os

from fastapi import FastAPI
import gradio as gr

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from app import demo

app = FastAPI()

app = gr.mount_gradio_app(
    app,
    demo,
    path="/"
)
