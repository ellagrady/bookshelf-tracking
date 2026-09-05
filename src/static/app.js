(() => {
  // Scanner pages share one dialog, so the script can stay independent of the current route.
  const dialog = document.querySelector('#scanner-dialog');
  const video = document.querySelector('#scanner-video');
  const status = document.querySelector('.scanner-status');
  const closeButton = document.querySelector('.dialog-close');
  let reader;
  let controls;
  let stopping = false;

  if (!dialog || !video) return;

  const stopScanner = () => {
    // Stop both ZXing and the browser media tracks before closing the dialog.
    if (stopping) return;
    stopping = true;
    try {
      controls?.stop();
      reader?.reset();
      video.srcObject?.getTracks().forEach((track) => track.stop());
      video.srcObject = null;
    } finally {
      controls = undefined;
      reader = undefined;
      stopping = false;
      if (dialog.open) dialog.close();
    }
  };

  document.querySelectorAll('[data-scanner-target]').forEach((button) => {
    button.addEventListener('click', async () => {
      // The button stores the target input so the same scanner works on lookup pages.
      const input = document.getElementById(button.dataset.scannerTarget);
      if (!window.ZXingBrowser) {
        dialog.showModal();
        status.textContent = 'Camera scanning is unavailable here. Enter the ISBN manually instead.';
        return;
      }
      stopping = false;
      reader = new ZXingBrowser.BrowserMultiFormatReader();
      dialog.showModal();
      status.textContent = 'Starting camera...';
      try {
        controls = await reader.decodeFromConstraints(
          { video: { facingMode: { ideal: 'environment' } } },
          video,
          (result, error) => {
            if (result) {
              // Keep the scanned value in the form; the user submits the lookup explicitly.
              input.value = result.getText().replace(/[^0-9X]/gi, '').toUpperCase();
              stopScanner();
              input.focus();
            } else if (error && error.name === 'NotAllowedError') {
              status.textContent = 'Camera permission was denied. Enter the ISBN manually instead.';
            }
          },
        );
        status.textContent = 'Point your camera at the barcode on the back of the book.';
      } catch (error) {
        status.textContent = error.name === 'NotAllowedError'
          ? 'Camera permission was denied. Enter the ISBN manually instead.'
          : 'Camera scanning is unavailable here. Enter the ISBN manually instead.';
      }
    });
    if (button.hasAttribute('data-scanner-autostart')) button.click();
  });

  closeButton.addEventListener('click', stopScanner);
  dialog.addEventListener('cancel', stopScanner);
})();
