---
channel: reddit
target: LocalLLaMA
title: An MCP harness where the LLM is never allowed to write a coordinate: it models 3D creatures from drawings (looking for contributors)
---
Instead of asking a model to "make a 3D bison", the harness gives it 14 MCP tools: observe (numeric digest, zoom, renders), act (a blueprint of parts and shape types; coordinate arguments are rejected), and verification gates whose criteria live inside the server. Three FAILs on the same gate lock the action tools until the model researches and changes its plan. A Rust state machine runs the criteria commands itself and ignores the model's own "it passed".

We're also measuring what the model can actually judge (part recognition, shape type, small parts, art quality) with known-answer quizzes and two model families in swapped order.

Real results so far: synthetic creatures volume IoU 0.92 vs 0.59 baseline; a real hand drawing still FAILs (flat head). Runs locally on old hardware (2 GB GPU), no paid APIs, MIT.

Issues have explicit pass conditions, and AI coding agents are welcome: https://github.com/endlessGold/Plastor
