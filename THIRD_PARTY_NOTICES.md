# Third-party notices

New code and documentation in this repository are MIT licensed. Dependencies retain their own licenses:

- Agno AgentOS, Apache-2.0: https://github.com/agno-agi/agno/blob/ab1d6007f09163c3adadbe06f998dc481b77a09a/LICENSE
- OpenResearch, MIT: https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/LICENSE
- React and Vite, MIT; FastAPI and SQLAlchemy, MIT; PostgreSQL, PostgreSQL License.

Agno is imported as a pinned dependency, not vendored or modified. OpenResearch is an optional external CLI; no upstream skills, service implementation or company workflows are copied. Keep upstream notices with any future redistributed third-party code. No commercial Control Plane assets are included.

The inert compressed `_virtualenv.py` test fixture in
`platform/tests/test_research_environment_observer.py` preserves the exact
uv 0.12.19 startup source (5246 bytes, SHA-256
`cfb3db86aaa53bb62b5ff764970bec2d71c9228590a0ebec57f6ec926cc0bf1a`).
It is never imported or executed by that test. Source:
https://github.com/astral-sh/uv/blob/0.12.19/crates/uv-virtualenv/src/_virtualenv.py
Uv is copyright (c) 2025 Astral Software Inc.; its MIT license is retained in
[`licenses/uv-MIT.txt`](licenses/uv-MIT.txt). The startup patch derives from
virtualenv, copyright (c) 2020-present The virtualenv developers; its MIT notice
is also retained in [`licenses/virtualenv-MIT.txt`](licenses/virtualenv-MIT.txt).
