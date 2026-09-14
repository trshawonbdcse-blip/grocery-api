import React, { useState, useEffect } from 'react';
import { createClient } from '@supabase/supabase-js';

// Replace with your Supabase credentials
const SUPABASE_URL = 'https://ocxnykaqirzvwimyvdtt.supabase.co';
const SUPABASE_ANON_KEY = 'YOUR_SUPABASE_ANON_KEY';
const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

// Haversine formula to calculate distance in km between two GPS coordinates
const calculateDistance = (lat1, lon1, lat2, lon2) => {
  if (!lat1 || !lon1 || !lat2 || !lon2) return null;
  const R = 6371; // Earth radius in km
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return (R * c).toFixed(1); // Returns distance rounded to 1 decimal
};

export default function FuelFinder() {
  const [userLocation, setUserLocation] = useState(null);
  const [stations, setStations] = useState([]);
  const [selectedFuel, setSelectedFuel] = useState('price_95'); // 'price_95', 'price_98', 'price_diesel'
  const [sortBy, setSortBy] = useState('price'); // 'price' or 'distance'
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState(null);

  // 1. Get User Location on Mount
  useEffect(() => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          setUserLocation({
            lat: position.coords.latitude,
            lon: position.coords.longitude,
          });
          fetchStations(position.coords.latitude, position.coords.longitude);
        },
        (err) => {
          setErrorMsg('Location access denied. Displaying general Tallinn stations.');
          fetchStations(59.437, 24.7535); // Fallback: Central Tallinn coordinates
        }
      );
    } else {
      setErrorMsg('Geolocation is not supported by your browser.');
      fetchStations(59.437, 24.7535);
    }
  }, []);

  // 2. Fetch Fuel Stations from Supabase
  const fetchStations = async (userLat, userLon) => {
    setLoading(true);
    const { data, error } = await supabase
      .from('fuel_stations')
      .select('*')
      .not('price_95', 'is', null);

    if (error) {
      console.error('Error fetching stations:', error);
      setLoading(false);
      return;
    }

    // Process distances
    const processed = data.map((station) => {
      const dist = calculateDistance(
        userLat,
        userLon,
        parseFloat(station.latitude),
        parseFloat(station.longitude)
      );
      return { ...station, distanceKm: dist ? parseFloat(dist) : 999 };
    });

    setStations(processed);
    setLoading(false);
  };

  // 3. Sort Stations Dynamically
  const sortedStations = [...stations].sort((a, b) => {
    if (sortBy === 'price') {
      return (a[selectedFuel] || 99) - (b[selectedFuel] || 99);
    } else {
      return a.distanceKm - b.distanceKm;
    }
  });

  const lowestPrice = Math.min(
    ...stations.map((s) => s[selectedFuel]).filter(Boolean)
  );

  return (
    <div style={styles.container}>
      <header style={styles.header}>
        <h2 style={{ margin: 0 }}>⛽ Fuel Finder Tallinn</h2>
        <p style={{ margin: '4px 0 0 0', opacity: 0.8, fontSize: '0.9rem' }}>
          Real-time lowest prices near your location
        </p>
      </header>

      {/* Fuel Type Switcher */}
      <div style={styles.controls}>
        <div style={styles.buttonGroup}>
          {['price_95', 'price_98', 'price_diesel'].map((fuelKey) => {
            const labels = {
              price_95: 'Euro 95',
              price_98: 'Euro 98',
              price_diesel: 'Diesel',
            };
            return (
              <button
                key={fuelKey}
                onClick={() => setSelectedFuel(fuelKey)}
                style={{
                  ...styles.fuelBtn,
                  ...(selectedFuel === fuelKey ? styles.fuelBtnActive : {}),
                }}
              >
                {labels[fuelKey]}
              </button>
            );
          })}
        </div>

        {/* Sort Switcher */}
        <div style={styles.sortContainer}>
          <label style={{ fontSize: '0.85rem', marginRight: '8px' }}>Sort by:</label>
          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value)}
            style={styles.select}
          >
            <option value="price">Cheapest Price</option>
            <option value="distance">Closest Distance</option>
          </select>
        </div>
      </div>

      {errorMsg && <div style={styles.errorNotice}>{errorMsg}</div>}

      {/* Station List */}
      {loading ? (
        <div style={styles.loading}>Searching nearest stations...</div>
      ) : (
        <div style={styles.list}>
          {sortedStations.map((station) => {
            const isCheapest = station[selectedFuel] === lowestPrice;
            const priceVal = station[selectedFuel]
              ? `€${parseFloat(station[selectedFuel]).toFixed(3)}`
              : 'N/A';

            return (
              <div
                key={station.id}
                style={{
                  ...styles.card,
                  ...(isCheapest ? styles.cheapestCard : {}),
                }}
              >
                <div style={styles.cardHeader}>
                  <div>
                    <span style={styles.brandBadge}>{station.brand}</span>
                    <h3 style={styles.stationName}>{station.station_name}</h3>
                    <p style={styles.address}>{station.address}</p>
                  </div>
                  <div style={styles.priceContainer}>
                    <span
                      style={{
                        ...styles.priceTag,
                        ...(isCheapest ? styles.cheapestTag : {}),
                      }}
                    >
                      {priceVal} <small>/L</small>
                    </span>
                    {isCheapest && <span style={styles.bestDealLabel}>BEST DEAL</span>}
                  </div>
                </div>

                <div style={styles.cardFooter}>
                  <span style={styles.distanceText}>
                    📍 {station.distanceKm < 900 ? `${station.distanceKm} km away` : 'Tallinn'}
                  </span>
                  <a
                    href={`https://www.google.com/maps/dir/?api=1&destination=${station.latitude},${station.longitude}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={styles.navBtn}
                  >
                    Navigate ↗
                  </a>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// Inline Styles (Clean Modern Dark Theme)
const styles = {
  container: {
    maxWidth: '500px',
    margin: '0 auto',
    padding: '16px',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    backgroundColor: '#121212',
    color: '#ffffff',
    minHeight: '100vh',
  },
  header: { marginBottom: '20px', textAlign: 'center' },
  controls: { display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '16px' },
  buttonGroup: { display: 'flex', gap: '8px', width: '100%' },
  fuelBtn: {
    flex: 1,
    padding: '10px 0',
    borderRadius: '8px',
    border: '1px solid #333',
    backgroundColor: '#1e1e1e',
    color: '#bbb',
    fontWeight: '600',
    cursor: 'pointer',
  },
  fuelBtnActive: { backgroundColor: '#2563eb', color: '#fff', borderColor: '#3b82f6' },
  sortContainer: { display: 'flex', alignItems: 'center', justifyContent: 'flex-end' },
  select: {
    padding: '6px 12px',
    borderRadius: '6px',
    backgroundColor: '#1e1e1e',
    color: '#fff',
    border: '1px solid #333',
  },
  errorNotice: {
    padding: '8px 12px',
    backgroundColor: '#371b1b',
    color: '#f87171',
    borderRadius: '6px',
    fontSize: '0.85rem',
    marginBottom: '12px',
  },
  loading: { textAlign: 'center', padding: '40px 0', color: '#888' },
  list: { display: 'flex', flexDirection: 'column', gap: '12px' },
  card: {
    backgroundColor: '#1e1e1e',
    borderRadius: '12px',
    padding: '16px',
    border: '1px solid #2a2a2a',
    boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
  },
  cheapestCard: { borderColor: '#10b981' },
  cardHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' },
  brandBadge: {
    fontSize: '0.75rem',
    fontWeight: '700',
    textTransform: 'uppercase',
    color: '#3b82f6',
    letterSpacing: '0.5px',
  },
  stationName: { margin: '4px 0 2px 0', fontSize: '1.1rem' },
  address: { margin: 0, fontSize: '0.85rem', color: '#aaa' },
  priceContainer: { display: 'flex', flexDirection: 'column', alignItems: 'flex-end' },
  priceTag: { fontSize: '1.4rem', fontWeight: '800', color: '#ffffff' },
  cheapestTag: { color: '#10b981' },
  bestDealLabel: {
    fontSize: '0.65rem',
    backgroundColor: '#10b981',
    color: '#000',
    padding: '2px 6px',
    borderRadius: '4px',
    fontWeight: '800',
    marginTop: '4px',
  },
  cardFooter: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: '16px',
    paddingTop: '12px',
    borderTop: '1px solid #2a2a2a',
  },
  distanceText: { fontSize: '0.85rem', color: '#888' },
  navBtn: {
    color: '#3b82f6',
    textDecoration: 'none',
    fontSize: '0.85rem',
    fontWeight: '600',
  },
};