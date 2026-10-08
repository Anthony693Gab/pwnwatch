# Publishing to the AUR

1. Create an account on https://aur.archlinux.org and add your SSH key.
2. Tag a release on GitHub (`git tag v0.5.0 && git push --tags`).
3. In this folder: replace `Anthony693Gab` and the maintainer line, then
   ```bash
   updpkgsums                 # fills in sha256sums from the GitHub tarball
   makepkg -si                # build + install locally to test
   makepkg --printsrcinfo > .SRCINFO
   ```
4. Push to the AUR:
   ```bash
   git clone ssh://aur@aur.archlinux.org/pwnwatch.git aur-pwnwatch
   cp PKGBUILD .SRCINFO aur-pwnwatch/
   cd aur-pwnwatch && git add . && git commit -m "pwnwatch 0.5.0" && git push
   ```
Users then install with `yay -S pwnwatch` (Omarchy ships `yay`).
For new versions bump `pkgver`, reset `pkgrel=1`, `updpkgsums`, regenerate `.SRCINFO`, push.
