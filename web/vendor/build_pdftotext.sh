#!/usr/bin/env bash
# Poppler's pdftotext as wasm: web/vendor/pdftotext.{js,wasm}. Same release as desktop.
# Needs emscripten (brew install emscripten), cmake and curl.

set -euo pipefail

VERSION=26.09.0
SHA256=8059eadb6805340768f138c465b57f8164c92b4a0773c37ef031ea6c0d987b2e
WEB=$(cd "$(dirname "$0")/.." && pwd)
WORK=${WORK:-$HOME/.cache/pdfexorcist-web}
export EM_CACHE=$WORK/emcache
mkdir -p "$WORK" "$EM_CACHE/sysroot/lib/pkgconfig"  # embuilder fails without it
cd "$WORK"

if [ ! -d poppler-$VERSION ]; then
  curl -sfLo poppler-$VERSION.tar.xz https://poppler.freedesktop.org/poppler-$VERSION.tar.xz
  echo "$SHA256  poppler-$VERSION.tar.xz" | shasum -a 256 -c -
  tar xJf poppler-$VERSION.tar.xz
fi
# emscripten's libc++ rejects a by-value unique_ptr of an incomplete type
sed -i.bak 's/explicit Object(std::unique_ptr<Array> arrayA)/explicit Object(std::unique_ptr<Array> \&\&arrayA)/' \
  poppler-$VERSION/poppler/Object.h

embuilder build zlib freetype libjpeg
S=$EM_CACHE/sysroot
L=$S/lib/wasm32-emscripten

rm -rf build && mkdir build && cd build
emcmake cmake ../poppler-$VERSION -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
  -DENABLE_UTILS=ON -DENABLE_CPP=OFF -DENABLE_GLIB=OFF -DENABLE_GOBJECT_INTROSPECTION=OFF \
  -DENABLE_QT5=OFF -DENABLE_QT6=OFF -DENABLE_BOOST=OFF -DENABLE_LIBOPENJPEG=OFF -DENABLE_LCMS=OFF \
  -DENABLE_LIBCURL=OFF -DENABLE_LIBTIFF=OFF -DENABLE_NSS3=OFF -DENABLE_GPGME=OFF \
  -DENABLE_HARFBUZZ=OFF -DBUILD_GTK_TESTS=OFF -DBUILD_QT5_TESTS=OFF -DBUILD_QT6_TESTS=OFF \
  -DBUILD_CPP_TESTS=OFF -DBUILD_MANUAL_TESTS=OFF -DRUN_GPERF_IF_PRESENT=OFF \
  -DFONT_CONFIGURATION=generic -DWITH_Cairo=OFF -DWITH_PNG=OFF \
  -DFREETYPE_INCLUDE_DIRS=$S/include/freetype2 -DFREETYPE_LIBRARY=$L/libfreetype.a \
  -DJPEG_INCLUDE_DIR=$S/include -DJPEG_LIBRARY=$L/libjpeg.a \
  -DZLIB_INCLUDE_DIR=$S/include -DZLIB_LIBRARY=$L/libz.a \
  -DCMAKE_EXE_LINKER_FLAGS="-sMODULARIZE=1 -sEXPORT_ES6=1 -sEXPORT_NAME=Pdftotext -sINVOKE_RUN=0 \
-sEXIT_RUNTIME=1 -sALLOW_MEMORY_GROWTH=1 -sENVIRONMENT=web,worker,node \
-sEXPORTED_RUNTIME_METHODS=callMain,FS -sFORCE_FILESYSTEM=1"
make -j"$(sysctl -n hw.ncpu 2>/dev/null || nproc)" pdftotext

mkdir -p "$WEB/vendor"
cp utils/pdftotext.js utils/pdftotext.wasm "$WEB/vendor/"
cp ../poppler-$VERSION/COPYING "$WEB/vendor/pdftotext.COPYING"  # GPL
cp ../poppler-$VERSION/COPYING3 "$WEB/vendor/pdftotext.COPYING3"
echo "Wrote $WEB/vendor/pdftotext.{js,wasm}"
