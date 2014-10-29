from setuptools import setup

setup(name="cerpcerus",
      version="0.1",
      description="Symmetrical, Secure RPC for Python",
      url="https://github.com/Dobatymo/cerpcerus",
      author="Hazzard",
      license="GPL",
      packages=["cerpcerus"],
      install_requires=["twisted", "msgpack-python", "pyOpenSSL"],
      zip_safe=True
)
