"use client";

import { FormEvent, useMemo, useState } from "react";

type ProductResult = {
  product: string;
  images: Record<string, string>;
};

type GenerationResponse = {
  run_id: string;
  campaign_id: string;
  products: ProductResult[];
  zip_path: string;
  manifest_path: string;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function HomePage() {
  const [campaignJson, setCampaignJson] = useState<File | null>(null);
  const [images, setImages] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<GenerationResponse | null>(null);

  const hasFiles = useMemo(() => Boolean(campaignJson), [campaignJson]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!campaignJson) {
      setError("Please upload a campaign.json file.");
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const formData = new FormData();
      formData.append("campaign_json", campaignJson);
      for (const image of images) {
        formData.append("images", image);
      }

      const response = await fetch(`${API_BASE}/generate`, {
        method: "POST",
        body: formData
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }

      const payload = (await response.json()) as GenerationResponse;
      setResult(payload);
    } catch (submitError) {
      setError(
        submitError instanceof Error ? submitError.message : "Failed to generate creatives."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main>
      <h1>Imagen Campaign Studio</h1>
      <p>Upload a campaign JSON plus source images to generate multi-ratio social ads.</p>

      <form className="card" onSubmit={onSubmit}>
        <p>
          <strong>Campaign JSON</strong>
        </p>
        <input
          type="file"
          accept=".json,application/json"
          onChange={(event) => setCampaignJson(event.target.files?.[0] ?? null)}
        />

        <p style={{ marginTop: "1rem" }}>
          <strong>Source Images (optional, multiple)</strong>
        </p>
        <input
          type="file"
          accept="image/*"
          multiple
          onChange={(event) => setImages(Array.from(event.target.files ?? []))}
        />

        <div style={{ marginTop: "1rem" }}>
          <button type="submit" disabled={loading || !hasFiles}>
            {loading ? "Generating..." : "Generate Campaign Assets"}
          </button>
        </div>
      </form>

      {error && (
        <div className="card" style={{ borderColor: "#ef4444", color: "#7f1d1d" }}>
          {error}
        </div>
      )}

      {result && (
        <section className="card">
          <h2>Run complete: {result.campaign_id}</h2>
          <p>
            <a href={`${API_BASE}${result.zip_path}`} target="_blank" rel="noreferrer">
              Download ZIP
            </a>{" "}
            |{" "}
            <a href={`${API_BASE}${result.manifest_path}`} target="_blank" rel="noreferrer">
              View Manifest
            </a>
          </p>

          {result.products.map((product) => (
            <div key={product.product} style={{ marginTop: "1.2rem" }}>
              <h3>{product.product}</h3>
              <div className="grid">
                {Object.entries(product.images).map(([ratio, src]) => (
                  <div className="preview" key={`${product.product}-${ratio}`}>
                    <p>{ratio}</p>
                    <img src={`${API_BASE}${src}`} alt={`${product.product} ${ratio}`} />
                  </div>
                ))}
              </div>
            </div>
          ))}
        </section>
      )}
    </main>
  );
}
