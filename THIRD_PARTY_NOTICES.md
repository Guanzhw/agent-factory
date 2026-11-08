# Third-party notices

New code and documentation in this repository are MIT licensed. Dependencies retain their own licenses:

- Agno AgentOS, Apache-2.0: https://github.com/agno-agi/agno/blob/ab1d6007f09163c3adadbe06f998dc481b77a09a/LICENSE
- OpenResearch, MIT: https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/LICENSE
- OpenCode 1.18.35, MIT: the exact `opencode-ai@1.18.35` package license is retained
  in [`licenses/opencode-MIT.txt`](licenses/opencode-MIT.txt). The original
  OpenResearch notice is retained in [`licenses/openresearch-MIT.txt`](licenses/openresearch-MIT.txt).
  SSH runtime distribution includes both notices, this notice inventory, and
  Factory's MIT license alongside the unchanged binaries and package code.
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

The same inert fixture collection also includes uv0.11.7 `_virtualenv.py`
(4342 bytes, SHA-256
`6cf30c56faf2a55228914dbbd17f8088ed371ebb08f5e7fa6fd931f913fcaf1d`).
It is not imported or executed. Source:
https://github.com/astral-sh/uv/blob/0.11.7/crates/uv-virtualenv/src/_virtualenv.py
The Astral and virtualenv MIT notices above apply to this fixture too.


### Setuptools 82.0.0 startup profile

The exact startup-file fixture and official wheel payload hash inventory are
derived from setuptools82.0.0 (MIT). The original license is retained at
`platform/tests/fixtures/setuptools82/LICENSE`. Official wheel source:
https://files.pythonhosted.org/packages/e1/c6/76dc613121b793286a3f91621d7b75a2b493e0390ddca50f11993eadf192/setuptools-82.0.0-py3-none-any.whl
Wheel SHA256:70b18734b607bd1da571d097d236cfcfacaf01de45717d59e6e04b96877532e0.
Only hashes and startup fixture text are included; vendored code is not copied.
The local profile explicitly enables the reviewed distutils shim and requires
complete installed inventory plus matching wheel payload. No compiler or runtime
compatibility result follows from these static pins.

## DeepSeek Harness visual reference

The conversation layout, dark colors, system font stack, and folded tool presentation refer to DeepSeek Harness 0.2.2-rc.1. Agent Factory retains its own React components, native Agno execution, and branding.

Source: https://github.com/deepseek-ai/deepseek-harness/tree/66491b05e3f05ad35bcdd4f6cd7ed26041d9e3db

Relevant sources: `apps/web`, `packages/bundle/web-app`, and the `packages/client/ui-theme`, `ui-sidebar`, `ui-chat`, and `ui-conversation` packages. The locally installed packages declare the same version and MIT license. The full notice follows.

MIT License

Copyright (c) 2026 DeepSeek

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
