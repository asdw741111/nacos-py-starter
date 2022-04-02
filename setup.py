import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="nacos-starter",
    version="1.0.1",
    author="chizongyang",
    author_email="chizongyang@aliyun.com",
    description="Nacos starter for python",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="",
    package_dir={"": "nacos-starter"},
    packages=setuptools.find_packages(where='nacos-starter'), # 自动查找模块
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.6",
)