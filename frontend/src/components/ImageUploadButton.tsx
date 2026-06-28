import { useRef, useState } from "react";
import { Loader2, Upload } from "lucide-react";

type Props = {
  onUpload: (file: File) => Promise<void>;
  disabled?: boolean;
  label?: string;
  className?: string;
  onError?: (message: string) => void;
};

export default function ImageUploadButton({
  onUpload,
  disabled,
  label = "上传图片",
  className = "btn-secondary text-xs",
  onError,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  const handleFile = async (file: File | undefined) => {
    if (!file || uploading || disabled) return;
    setUploading(true);
    try {
      await onUpload(file);
    } catch (e) {
      onError?.(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        disabled={disabled || uploading}
        onChange={(e) => void handleFile(e.target.files?.[0])}
      />
      <button
        type="button"
        className={className}
        disabled={disabled || uploading}
        onClick={() => inputRef.current?.click()}
      >
        {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
        {label}
      </button>
    </>
  );
}
