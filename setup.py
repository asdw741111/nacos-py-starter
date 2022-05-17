"""
build for publish script.
"""
import re

import setuptools

module_dir = "nacos_starter"

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open(f"src/{module_dir}/__init__.py", encoding="utf-8") as fh:
    lines = fh.readlines()
    vl = [x for x in lines if "__version__" in x][0]
    version = re.sub(r"[^\d.]", "", str.strip(vl.split("=")[1]))
    namel = [x for x in lines if "name" in x][0]
    name = re.sub(r"[^\w\-_]", "", str.strip(namel.split("=")[1]))
# read dependencies from requirements.txt
install_requires=[line.strip() for line in open("requirements.txt").readlines()]

setuptools.setup(
    name=name,
    version=version,
    author="chizongyang",
    author_email="chizongyang@aliyun.com",
    description="Nacos starter for python",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="",
    include_package_data=True,
    package_dir={"": "src"},
    # 自动查找模块
    packages=setuptools.find_packages(where="src"),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent"
    ],
    install_requires=install_requires,
    python_requires=">=3.6",
)
