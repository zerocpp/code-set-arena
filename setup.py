from setuptools import find_packages, setup


setup(
    name="code-set-arena",
    version="7.1.3",
    description="CodeSetArena local course system",
    package_dir={"": "src"},
    packages=find_packages("src"),
    include_package_data=True,
    python_requires=">=3.11",
    install_requires=[
        "fastapi>=0.111",
        "jinja2>=3.1",
        "python-multipart>=0.0.9",
        "typer>=0.12",
        "uvicorn>=0.30",
    ],
    extras_require={
        "dev": [
            "httpx>=0.27",
            "pytest>=8",
            "ruff>=0.5",
        ]
    },
    entry_points={"console_scripts": ["code-set-arena=codesetarena.cli:app"]},
)
