from setuptools import setup, find_packages

setup(
    name="llm-provider",
    version="0.1.0",
    description="LLM Provider Abstraction Layer with intelligent routing",
    author="AI Native Team",
    packages=find_packages(),
    install_requires=[
        "httpx>=0.24.0",
        "pyyaml>=6.0",
    ],
    extras_require={
        "anthropic": ["anthropic>=0.18.0"],
    },
    python_requires=">=3.9",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
