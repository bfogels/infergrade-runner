"""Legacy editable-install bridge for older pip versions."""

from setuptools import find_packages, setup


setup(
    name="infergrade-runner-core",
    version="0.3.2",
    description="Portable benchmarking runner core for InferGrade.",
    author="Brian Fogelson",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "infergrade=infergrade.cli:main",
        ],
    },
)
