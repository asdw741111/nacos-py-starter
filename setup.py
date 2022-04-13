"""
build for publish script.
"""
import setuptools
import re

module_dir = "nacos_starter"

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open(f"{module_dir}/__init__.py", encoding="utf-8") as fh:
    lines = fh.readlines()
    vl = [x for x in lines if "__version__" in x][0]
    version = re.sub(r"[^\d.]", "", str.strip(vl.split("=")[1]))
    namel = [x for x in lines if "name" in x][0]
    name = re.sub(r"[^\w\-_]", "", str.strip(namel.split("=")[1]))

setuptools.setup(
    name=name,
    version=version,
    author="chizongyang",
    author_email="chizongyang@aliyun.com",
    description="Nacos starter for python",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="",
    package_dir={"": module_dir},
    packages=setuptools.find_packages(where="nacos-starter"), # 自动查找模块
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.6",
)
