from setuptools import setup

extras = {
	"websockets": ["autobahn"],
	"twisted warning": ["service_identity"]
}

setup(name="cerpcerus",
	version="0.2",
	description="Symmetrical, Secure RPC for Python",
	url="https://github.com/Dobatymo/cerpcerus",
	author="Dobatymo",
	license="GPL",
	packages=["cerpcerus"],
	test_suite="test",
	install_requires=[
		"future",
		"twisted",
		"msgpack>=0.6.0",
		"pyOpenSSL",
		"funcsigs;python_version<'3.3'"],
	extras_require=extras,
	use_2to3=False,
	zip_safe=True
)
