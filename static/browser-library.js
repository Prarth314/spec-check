/* IndexedDB holds each hosted visitor's PDF library across page reloads.
 * No shared server filesystem or third-party storage account is required.
 */
window.SpecCheckLibrary = (() => {
  let database;
  async function open() {
    if (database) return database;
    if (!window.indexedDB) throw new Error('This browser cannot save a PDF library. Enable browser storage or use the local app.');
    database = await new Promise((resolve, reject) => {
      const request = indexedDB.open('spec-check-library', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('documents', {keyPath:'id'});
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(new Error('Browser storage is unavailable. Allow site storage to keep your PDFs.'));
    });
    database.onversionchange = () => { database.close(); database = null; };
    return database;
  }
  async function transact(mode, action) {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('documents', mode);
      const request = action(tx.objectStore('documents'));
      tx.oncomplete = () => resolve(request.result);
      tx.onabort = tx.onerror = () => reject(new Error('Unable to access the browser library. Check available storage and try again.'));
    });
  }
  return {
    open,
    async list() {
      const docs = await transact('readonly', store => store.getAll());
      return docs.map(({pdf, extracted_chunks, ...metadata}) => metadata)
        .sort((a,b) => a.created_at.localeCompare(b.created_at));
    },
    get(id) { return transact('readonly', store => store.get(id)); },
    put(doc) { return transact('readwrite', store => store.put(doc)); },
    delete(id) { return transact('readwrite', store => store.delete(id)); }
  };
})();
