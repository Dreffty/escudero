# Empaqueta Escudero como una app de macOS de verdad (Escudero.app) con py2app:
# lleva dentro su propio Python y sus dependencias, vive en la barra de menús
# sin icono en el Dock y los permisos de macOS se le atribuyen a «Escudero».
# No lo llames a mano: usa ./instalar.sh
from setuptools import setup

MODULOS = ["api", "atajos", "autoarranque", "cortina", "cronica", "lector",
           "ordenar", "panel_pergamino", "pergamino", "sequito", "ventanas", "vigia"]

setup(
    name="Escudero",
    app=["escudero.py"],
    data_files=["config.ejemplo.yaml"],
    py_modules=MODULOS,
    options={"py2app": {
        "packages": ["escudero", "rumps", "pydantic", "pydantic_core", "yaml"],
        "includes": MODULOS + ["ServiceManagement", "Vision", "Quartz",
                               "ApplicationServices", "AppKit", "Foundation"],
        "plist": {
            "CFBundleName": "Escudero",
            "CFBundleDisplayName": "Escudero",
            "CFBundleIdentifier": "com.escudero.mayordomo",
            "CFBundleShortVersionString": "1.1",
            "CFBundleVersion": "2",
            "LSUIElement": True,
            "LSMinimumSystemVersion": "13.0",
            "NSHighResolutionCapable": True,
            "NSAppleEventsUsageDescription":
                "Escudero usa System Events para mover y encajar ventanas.",
        },
    }},
)
