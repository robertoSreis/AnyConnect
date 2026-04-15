This project already works on my machine, but I need other people to test and configure it to see if it works on different machines, or if each machine has its own way of running it. Please note that this project is experimental and should not be used irresponsibly or with malicious code.

Compile: python -m nuitka --standalone --enable-plugin=pyqt6 --include-data-dir=* --pgo-python --windows-icon-from-ico=marca-preta.ico --output-dir=dist --output-filename=SE3D.exe --company-name="SE3D" --product-name="SE3D GESTÃO" --clang --lto=yes --file-version=1.0.3.73 --windows-console-mode=disable main.py

www.se3d.com.br/anyconnect
