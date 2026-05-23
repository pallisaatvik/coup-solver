# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`coup-solver` is a solver/analysis tool for the card game [Coup](https://en.wikipedia.org/wiki/Coup_(card_game)). The project is in its initial state — no source code exists yet.

Update this file as the project takes shape: add build/test/run commands, language/framework choices, and architecture notes once they are established.

## Deployment

This project is deployed on [Railway](https://railway.app). Pushes to the main branch trigger automatic deploys.

## Permissions

When running on a Linux server, Claude is authorized to commit and push changes without asking for confirmation.

After any prompt that results in code being written or modified in this repo, automatically commit and push the changes.

When the user is coding from their phone or hosting a remote control session, Claude is authorized to run bash commands and search the internet without asking for confirmation.

## User context

The user often codes from their phone. When they provide a bash command to run, include the full output inline in the chat response (not just as a tool result).
