.. _Postman: https://www.postman.com/
.. _FastAPI: https://fastapi.tiangolo.com/
.. _flask2postman: https://github.com/numberly/flask2postman/

================
fastapi2postman
================

.. image:: https://img.shields.io/pypi/v/flask2postman.svg
   :target: https://pypi.org/project/fastapi2postman
.. image:: https://img.shields.io/github/license/numberly/flask2postman.svg
   :target: https://github.com/ashhadahsan/fastapi2postman/blob/main/LICENSE

|

A tool that creates a Postman_ collection from a FastAPI_ application.

Inspired from flask2postman_


Install
=======

.. code-block:: sh

    $ pip install fastapi2postman


Example
=======

Let's say that you have a FastAPI project called "app.py"  and you want to generate a Postman collection out of it.

You just need to tell :code:`fastapi2postman` 

.. code-block:: sh

    $ fastapi2postman --app app.py 

If you want to change the name of the output file use --output flag, the default name is ofcousre output.json

.. code-block:: sh

    $ fastapi2postman --app app.py --output output.json

This will generate the JSON configuration, and write it into the
:code:`output.json` file. You can then import this file into Postman ("Import
Collection" button), and profit:

On a side note, you can see that endpoint's docstrings are automatically
imported as descriptions.


Usage
=====

.. code-block:: sh

    usage: fastapi2postman [-h] [--output OUTPUT] [--name NAME] [--host HOST]
                       [--port PORT] --app APP

optional arguments:
  -h, --help       show this help message and exit
  --output OUTPUT  Output file
  --name NAME      Collection name
  --host HOST      API host
  --port PORT      API port
  --app APP        Path to FastAPI application instance


License
=======

MIT