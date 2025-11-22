from setuptools import setup
import os

def package_data(pkg, roots):
    data = []
    for root in roots:
        for dirname, _, files in os.walk(os.path.join(pkg, root)):
            for f in files:
                data.append(os.path.relpath(os.path.join(dirname, f), pkg))
    return {pkg: data}

setup(
    name='ptexblock-xblock',
    version='0.4',
    description='Minimal PTE XBlock',
    packages=['ptexblock'],
    entry_points={
        'xblock.v1': [
            'ptexblock = ptexblock.ptexblock:PTEXBlock',
        ]
    },
    package_data=package_data("ptexblock", ["static", "public", "templates"]),
    include_package_data=True,
)
 