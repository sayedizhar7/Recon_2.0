import { useState } from "react";
import axios from "axios";

const BASE = "http://localhost:8001";

export default function FileUpload({ onUploadComplete, uploading, setUploading }) {
  const [source, setSource] = useState(null);
  const [dest, setDest] = useState(null);

  const upload = async () => {
    if (!source || !dest) {
      alert("Please select both files");
      return;
    }

    try {
      setUploading(true);

      const formData = new FormData();
      formData.append("source", source);
      formData.append("dest", dest);

      const res = await axios.post(`${BASE}/upload`, formData);

      if (res.data.error) {
        alert(res.data.error);
        setUploading(false);
        return;
      }

      onUploadComplete(res.data);
    } catch (err) {
      console.error(err);
      alert("Upload failed");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="bg-white p-5 rounded-xl shadow">
      <h2 className="text-lg font-bold mb-3">Upload Files</h2>

      <input type="file" onChange={(e) => setSource(e.target.files[0])} />
      <br /><br />
      <input type="file" onChange={(e) => setDest(e.target.files[0])} />
      <br /><br />

      <button
        onClick={upload}
        disabled={uploading}
        className="bg-blue-600 text-white px-4 py-2 rounded"
      >
        {uploading ? "Uploading..." : "Upload Files"}
      </button>
    </div>
  );
}