from setuptools import setup

extras = {
	"websockets": ["autobahn"],
	"twisted warning": ["service_identity"]
}

# msgpack-python 0.4.2: exceptions.MemoryError

setup(name="cerpcerus",
	version="0.2",
	description="Symmetrical, Secure RPC for Python",
	url="https://github.com/Dobatymo/cerpcerus",
	author="Hazzard",
	license="GPL",
	packages=["cerpcerus"],
	test_suite="tests",
	install_requires=["twisted", "msgpack-python", "pyOpenSSL", "funcsigs"],
	extras_require=extras,
	use_2to3=True,
	zip_safe=True
)
