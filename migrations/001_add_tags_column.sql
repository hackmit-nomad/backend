-- Add tags column to profiles table for skill/expertise tags
-- Run this in Supabase SQL Editor
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS tags json DEFAULT '[]'::json;
