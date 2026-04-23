-- =====================================================
-- RealEstork Database Schema v2.1
-- Supabase (PostgreSQL)
-- Run in Supabase SQL Editor
-- =====================================================

-- Core listings table
CREATE TABLE IF NOT EXISTS listings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,
    source_id TEXT,
    source_url TEXT,
    title TEXT,
    description TEXT,
    address TEXT,
    address_normalized TEXT,         -- Normalized for dedup (unidecode, lowercase)
    district TEXT,
    city TEXT DEFAULT 'HCMC',
    area_m2 NUMERIC,
    floor_level INTEGER,             -- 1=tầng trệt, 2=lầu 1, etc. NULL=unknown
    price_vnd_monthly BIGINT,
    price_text TEXT,
    phone TEXT,
    contact_name TEXT,
    images TEXT[],
    posted_at TIMESTAMPTZ,
    scraped_at TIMESTAMPTZ DEFAULT NOW(),
    listing_age_hours NUMERIC,       -- Computed at scrape time (posted_at → scraped_at)
    content_hash TEXT,               -- SHA256(title+phone+description[:100])

    -- Classification
    classification_score INTEGER DEFAULT 50,
    classification_label TEXT DEFAULT 'can_xac_minh',
    -- Values: chinh_chu, can_xac_minh, moi_gioi
    ai_result JSONB,                 -- {is_owner_probability, reasoning, signals_detected}
    osint_result JSONB,              -- {zalo, truecaller, google_count, internal_count}

    -- Status tracking (vợ workflow)
    status TEXT DEFAULT 'new',
    -- Values: new, alerted, called, confirmed_owner, confirmed_broker, archived
    notes TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(source, source_id)
);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_listings_updated_at
    BEFORE UPDATE ON listings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Phone frequency tracking
CREATE TABLE IF NOT EXISTS phones (
    phone TEXT PRIMARY KEY,
    total_listings INTEGER DEFAULT 0,
    platforms TEXT[],                -- Which platforms this phone appeared on
    platform_count INTEGER DEFAULT 0, -- len(platforms) for easy query
    max_single_platform INTEGER DEFAULT 0, -- Max listings on any 1 platform
    first_seen TIMESTAMPTZ DEFAULT NOW(),
    last_seen TIMESTAMPTZ DEFAULT NOW(),
    is_known_broker BOOLEAN DEFAULT FALSE,
    broker_company TEXT,
    -- OSINT results (cached)
    zalo_name TEXT,
    zalo_is_business BOOLEAN,
    truecaller_name TEXT,
    truecaller_is_business BOOLEAN,
    google_result_count INTEGER,
    trangtrang_spam BOOLEAN,
    notes TEXT
);

-- Known broker phone database
-- Seeded from vợ's knowledge + auto-detected over time
CREATE TABLE IF NOT EXISTS broker_phones (
    phone TEXT PRIMARY KEY,
    name TEXT,
    company TEXT,
    source TEXT DEFAULT 'manual',  -- "manual", "confirmed_by_wife", "auto_detected"
    confidence NUMERIC DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Classification feedback (learning loop)
-- Populated via /mark commands from vợ's Zalo
CREATE TABLE IF NOT EXISTS classification_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    listing_id UUID REFERENCES listings(id),
    predicted_label TEXT,
    predicted_score INTEGER,
    actual_label TEXT,  -- "chinh_chu" or "moi_gioi" (confirmed by human)
    feedback_source TEXT,  -- "wife_zalo", "subscriber_telegram"
    signals_at_prediction JSONB,  -- Snapshot: {signal_name: contribution, ...}
    ai_model_used TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Alert subscribers (Hướng 2 product)
CREATE TABLE IF NOT EXISTS alert_subscribers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_chat_id BIGINT UNIQUE,
    discord_user_id TEXT,
    discord_channel_id TEXT,
    name TEXT,
    district_filter TEXT[],         -- Empty = all districts
    min_price BIGINT DEFAULT 0,
    max_price BIGINT DEFAULT 999999999,
    min_score INTEGER DEFAULT 60,
    subscription_tier TEXT DEFAULT 'free',
    -- Values: free, basic, premium
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Company listings (Phase 2 — from company DB extraction)
CREATE TABLE IF NOT EXISTS company_listings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    address TEXT,
    address_normalized TEXT,
    district TEXT,
    area_m2 NUMERIC,
    floor_level INTEGER,
    price_vnd_monthly BIGINT,
    commission_months NUMERIC,
    commission_rate NUMERIC,
    lease_status TEXT DEFAULT 'available',
    -- Values: available, rented, expired
    tenant_name TEXT,
    lease_end_date DATE,
    -- NOTE: owner_phone and owner_name NOT stored here for privacy
    -- Only internal cross-reference use
    imported_at TIMESTAMPTZ DEFAULT NOW(),
    extraction_session_id TEXT,     -- Which extraction session added this
    source_notes TEXT
);

-- Spider execution logs
CREATE TABLE IF NOT EXISTS spider_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    spider_name TEXT NOT NULL,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status TEXT,  -- "success", "partial", "failed"
    listings_found INTEGER DEFAULT 0,
    new_listings INTEGER DEFAULT 0,
    error_message TEXT,
    duration_seconds NUMERIC
);

-- =====================================================
-- INDEXES (for query performance)
-- =====================================================

CREATE INDEX IF NOT EXISTS idx_listings_phone ON listings(phone);
CREATE INDEX IF NOT EXISTS idx_listings_district ON listings(district);
CREATE INDEX IF NOT EXISTS idx_listings_score ON listings(classification_score DESC);
CREATE INDEX IF NOT EXISTS idx_listings_scraped ON listings(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status);
CREATE INDEX IF NOT EXISTS idx_listings_source ON listings(source);
CREATE INDEX IF NOT EXISTS idx_listings_hash ON listings(content_hash);
CREATE INDEX IF NOT EXISTS idx_listings_label ON listings(classification_label);
CREATE INDEX IF NOT EXISTS idx_listings_posted ON listings(posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_listings_age ON listings(listing_age_hours);
CREATE INDEX IF NOT EXISTS idx_listings_floor ON listings(floor_level);

CREATE INDEX IF NOT EXISTS idx_phones_broker ON phones(is_known_broker);
CREATE INDEX IF NOT EXISTS idx_phones_platforms ON phones USING GIN(platforms);

CREATE INDEX IF NOT EXISTS idx_company_district ON company_listings(district);
CREATE INDEX IF NOT EXISTS idx_company_status ON company_listings(lease_status);

CREATE INDEX IF NOT EXISTS idx_feedback_listing ON classification_feedback(listing_id);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON classification_feedback(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_spider_logs_name ON spider_logs(spider_name);
CREATE INDEX IF NOT EXISTS idx_spider_logs_started ON spider_logs(started_at DESC);

CREATE INDEX IF NOT EXISTS idx_subscribers_telegram ON alert_subscribers(telegram_chat_id);
CREATE INDEX IF NOT EXISTS idx_subscribers_tier ON alert_subscribers(subscription_tier);
CREATE INDEX IF NOT EXISTS idx_subscribers_active ON alert_subscribers(is_active);

-- =====================================================
-- ROW LEVEL SECURITY (optional for future Web UI)
-- =====================================================

-- For now, service role key bypasses RLS
-- Enable when building Web UI auth layer:
-- ALTER TABLE listings ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE alert_subscribers ENABLE ROW LEVEL SECURITY;
