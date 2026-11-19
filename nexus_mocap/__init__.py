"""NEXUS: ayudas para revisar grabaciones de captura de movimiento (C3D).

Principios del proyecto:

* El archivo original nunca se modifica. Todo lo que se calcula es una propuesta.
* Los movimientos reales del paciente (temblor, discinesias, bloqueos) no son
  errores. Ante la duda, se señala para revisar y no se propone corrección.
* Los datos se procesan en local; nada se envía a servicios externos.
"""

__version__ = "0.1.0"
