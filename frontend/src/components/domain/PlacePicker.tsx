import { useEffect, useId, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { JourneyPlace } from "../../api/types";
import { Icon } from "../ui/Icon";

interface PlacePickerProps {
  label: string;
  value: JourneyPlace | null;
  onChange: (place: JourneyPlace | null) => void;
  placeholder?: string;
  error?: string | null;
  disabled?: boolean;
}

/** Airport and rail-station lookup backed by the loaded reference datasets. */
export function PlacePicker({
  label,
  value,
  onChange,
  placeholder = "City, airport or station code",
  error,
  disabled,
}: PlacePickerProps) {
  const id = useId();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);

  const results = useQuery({
    queryKey: ["journey-places", query],
    queryFn: () => api.journeyPlaces(query),
    enabled: query.trim().length >= 2 && open,
    staleTime: 5 * 60 * 1000,
  });

  const places = results.data?.places ?? [];

  useEffect(() => {
    function onDocumentClick(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocumentClick);
    return () => document.removeEventListener("mousedown", onDocumentClick);
  }, []);

  useEffect(() => {
    setHighlight(0);
  }, [query]);

  function select(place: JourneyPlace) {
    onChange(place);
    setQuery("");
    setOpen(false);
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (!open || places.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlight((h) => Math.min(h + 1, places.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      select(places[highlight]);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className="field" ref={rootRef}>
      <label className="field__label" htmlFor={id}>
        {label}
      </label>

      {value ? (
        <div className="picker-value">
          <Icon name={value.kind === "rail" ? "TrainFront" : value.kind === "city" ? "Building2" : value.kind === "bus" ? "Bus" : "Plane"} size={15} />
          <span className="picker-value__code">{value.code}</span>
          <span className="picker-value__name">
            {value.name} · {value.city}, {value.country}
          </span>
          <button
            type="button"
            className="btn btn--icon btn--sm btn--ghost"
            aria-label={`Clear ${label}`}
            onClick={() => {
              onChange(null);
              setQuery("");
            }}
            disabled={disabled}
          >
            <Icon name="X" size={14} />
          </button>
        </div>
      ) : (
        <div className="picker-search">
          <Icon name="Search" size={15} />
          <input
            id={id}
            className="input input--search"
            type="text"
            role="combobox"
            aria-expanded={open}
            aria-controls={`${id}-list`}
            aria-autocomplete="list"
            value={query}
            placeholder={placeholder}
            disabled={disabled}
            aria-invalid={error ? true : undefined}
            onChange={(event) => {
              setQuery(event.target.value);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            onKeyDown={onKeyDown}
          />
        </div>
      )}

      {open && !value ? (
        <div className="picker-menu" id={`${id}-list`} role="listbox">
          {query.trim().length < 2 ? (
            <div className="picker-menu__hint">Type at least two characters.</div>
          ) : results.isLoading ? (
            <div className="picker-menu__hint">Searching reference data…</div>
          ) : places.length === 0 ? (
            <div className="picker-menu__hint">No city, airport or station matches that.</div>
          ) : (
            places.map((place, index) => (
              <button
                key={place.code}
                type="button"
                role="option"
                aria-selected={index === highlight}
                className={`picker-option${index === highlight ? " is-active" : ""}`}
                onMouseEnter={() => setHighlight(index)}
                onClick={() => select(place)}
              >
                <Icon
                  name={place.kind === "rail" ? "TrainFront" : place.kind === "city" ? "Building2" : "Plane"}
                  size={14}
                />
                <span className="picker-option__code">{place.code}</span>
                <span className="picker-option__name">{place.name}</span>
                <span className="picker-option__meta">
                  {place.city} · {place.country}
                </span>
              </button>
            ))
          )}
        </div>
      ) : null}

      {error ? <div className="field__error">{error}</div> : null}
    </div>
  );
}
