How-to guides
=============

These guides provide instructions for performing different operations with `chimg`.

Install chimg
-------------

`chimg` is available as a snap on the snapstore:

.. code-block:: shell

    sudo snap install chimg --classic

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

Create and upload files to a given chroot directory
---------------------------------------------------

.. literalinclude:: ../config-samples/config-files-only.yaml
   :language: yaml

Apply those changes to a given chroot directory (in this case `/path/to/chroot/`)
with:

.. code-block:: shell

   sudo chimg --log-console chrootfs docs/config-samples/config-files-only.yaml /path/to/chroot/

Integration with livecd-rootfs
------------------------------

`chimg` does integrate well with `livecd-rootfs`. Eg. `chimg` respects existing mount points
which means it doesn't try to mount eg `/dev/` if that is already mounted within the given
chroot directory.
`chimg` can be called multiple times with different configuration files.

Testing a configuration
-----------------------

The easiest way to test a given configuration is usually to use
an existing chroot directory. Creating a new chroot dir can be done with:

.. code-block:: shell

    sudo mmdebstrap --variant=apt --verbose noble /chimg-noble

Then applying a config to that chroot directory can be done via:

.. code-block:: shell

    sudo chimg --log-console chrootfs config.yaml /tmp/noble

The applied changes can be manually verified by entering the chroot via:

.. code-block:: shell

    sudo chroot /tmp/noble
