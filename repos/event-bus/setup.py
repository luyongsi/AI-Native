from setuptools import setup, find_packages

setup(
    name="event-bus",
    version="0.1.0",
    description="NATS JetStream-based async event bus for the ai-native platform",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "nats-py>=0.10.1",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-asyncio>=0.21",
        ],
    },
    author="ai-native",
    license="MIT",
)
