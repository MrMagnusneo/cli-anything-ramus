#!/usr/bin/env python3
"""setup.py for cli-anything-ramus.

Install with: pip install -e .
Or publish to PyPI: python -m build && twine upload dist/*
"""

import os

from setuptools import find_namespace_packages, setup

HERE = os.path.abspath(os.path.dirname(__file__))

with open(os.path.join(HERE, "cli_anything", "ramus", "README.md"), encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="cli-anything-ramus",
    version="1.0.0",
    author="cli-anything contributors",
    author_email="",
    description=(
        "CLI harness for Ramus - headless IDEF0/DFD business process modelling and diagram "
        "rendering. Requires: a Ramus build (ramus.jar) and a JDK."
    ),
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/HKUDS/CLI-Anything",
    packages=find_namespace_packages(include=["cli_anything.*"]),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Office/Business",
        "Topic :: Multimedia :: Graphics :: Editors :: Vector-Based",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.10",
    install_requires=[
        "click>=8.0.0",
        "prompt-toolkit>=3.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "cli-anything-ramus=cli_anything.ramus.ramus_cli:main",
        ],
    },
    package_data={
        "cli_anything.ramus": ["skills/*.md", "README.md"],
        # The Java bridge is compiled against the user's ramus.jar on first use,
        # so its sources must ship with the package.
        "cli_anything.ramus.utils": ["java/com/cliany/ramus/*.java"],
    },
    include_package_data=True,
    zip_safe=False,
)
