How-to guides
=============

These guides provide instructions for performing different operations with `chimg`.

Install debian packages in a given chroot directory
---------------------------------------------------

The following `config.yaml` will install some debian packages:

.. literalinclude:: ../config-samples/config-deb-only.yaml
   :language: yaml

Apply those changes to a given chroot directory (in this case `/path/to/chroot/`)
with:

.. code-block:: shell

   sudo chimg --log-console chrootfs config.yaml /path/to/chroot/

Replace a kernel in a given chroot directory
--------------------------------------------

.. literalinclude:: ../config-samples/config-kernel-only.yaml
   :language: yaml

Apply those changes to a given chroot directory (in this case `/path/to/chroot/`)
with:

.. code-block:: shell

   sudo chimg --log-console chrootfs config.yaml /path/to/chroot/
