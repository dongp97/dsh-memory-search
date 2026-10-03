from setuptools import setup, find_packages

setup(
    name="dsh-memory-search",
    version="1.0.0",
    description="DSH 会话记忆智能检索工具 — 基于 SQLite FTS5 全文检索",
    author="dongp97",
    packages=find_packages(),
    python_requires=">=3.10",
    entry_points={
        "console_scripts": [
            "dsh-memory=src.main:main",
        ],
    },
)
