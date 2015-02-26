from setuptools import setup

setup(name="cerpcerus",
      version="0.1",
      description="Symmetrical, Secure RPC for Python",
      url="https://github.com/Dobatymo/cerpcerus",
      author="Hazzard",
      license="GPL",
      packages=["cerpcerus"],
      test_suite="tests",
      install_requires=["twisted", "msgpack-python", "pyOpenSSL"],
      use_2to3=True,
      zip_safe=True
)
