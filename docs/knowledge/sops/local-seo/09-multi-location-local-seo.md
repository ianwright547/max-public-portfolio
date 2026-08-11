---
title: Multi-location Local SEO SOP
slug: multi-location-local-seo
knowledge_type: sop
version: "1.0.0"
status: proposed
owner: agency
humanizer_required: true
---

# Multi-location Local SEO SOP

## Purpose

This SOP controls Local SEO for brands with several eligible locations, franchises, branches, offices, practitioners, or service operations.

Its main job is to keep brand facts and location facts accurate without mixing records.

## Core principles

- One brand record does not replace location records.
- Every location must be independently eligible.
- Every public profile must represent a real operation.
- Shared language may be reused only when the facts are shared.
- Local facts, staff, reviews, hours, services, and results must stay attached to the correct location.
- Rollup reports must show how totals were calculated.
- A page does not create location eligibility.
- A service area does not create a branch.

## Data structure

Maintain:

### Brand record

- brand name
- legal entity
- main website
- approved brand voice
- shared services
- shared qualifications
- shared policies
- shared proof
- prohibited claims
- central approver

### Location record

- location ID
- public name
- eligibility type
- profile identifier
- physical address or hidden-address status
- phone
- location page
- hours
- categories
- services
- service areas
- staff
- location proof
- review link
- local approver
- opening date
- status
- reporting sources

Do not store a shared value as local when it varies.

## Step 1: Confirm location eligibility

For each location, confirm:

- real operation
- customer access when a storefront is claimed
- staff presence
- separate operation where required
- permanent identification
- valid phone routing
- real hours
- accurate address handling
- separate profile eligibility
- relationship to the brand

Classify:

- eligible storefront
- eligible service-area operation
- eligible hybrid
- eligible practitioner
- eligible department
- duplicate
- old location
- planned location
- ineligible
- unknown

A planned location must not be published as open.

## Step 2: Create the location roster

Maintain one controlled roster with:

- current locations
- planned locations
- moved locations
- closed locations
- merged locations
- duplicates
- temporary closures
- ownership changes

Use stable location IDs. Do not use only the city name when several locations share a city.

## Step 3: Control naming

The public profile name must match the real-world location name.

Do not append:

- city
- neighborhood
- service
- slogan
- hours
- keywords

unless the wording is part of the real public name.

Location page titles may include the place and service when accurate. The profile name rule is separate.

## Step 4: Control categories and services

Set brand standards, then allow documented local exceptions.

For each location:

- confirm primary category
- confirm secondary categories
- confirm active services
- confirm service hours
- confirm local exclusions
- map services to local pages
- record who approved exceptions

Do not apply a service to every location because the brand offers it somewhere.

## Step 5: Control NAP and phone routing

Each location must have:

- approved public name
- approved address or hidden-address status
- approved phone
- approved location page
- accurate hours

Phone rules:

- calls must reach the correct location or routing group
- tracking numbers must remain documented
- failure paths must be tested
- after-hours behavior must be known
- one location's number must not appear on another location's profile without an approved routing reason

## Step 6: Create location pages

Every eligible physical location should have a useful location page.

Include as appropriate:

- approved NAP
- hours
- services offered there
- staff
- real location assets
- access information
- local proof
- location contact path
- structured data
- internal links

For service-area operations, use truthful service-area language and do not imply an office.

Shared sections may include brand facts. Local sections must use location-specific evidence.

Do not create pages by changing only the place name.

## Step 7: Manage shared and local content

Classify facts as:

- brand-wide
- location-specific
- service-specific
- temporary
- unknown

Allowed shared material:

- verified brand history
- central policies
- shared service process
- shared qualifications
- approved general FAQs

Required local material when claimed:

- location NAP
- local hours
- local staff
- local service availability
- local proof
- local access
- local service area
- local phone
- location-specific reviews

Do not copy a local testimonial to every location.

## Step 8: Build the site hierarchy

Typical structure:

```text
homepage
  -> locations index
      -> location page
          -> services available at that location
          -> local supporting blogs
```

Also link:

- service pages to locations offering the service
- location pages to relevant service pages
- blogs to the correct location or service
- nearby locations only when useful
- breadcrumbs through the correct hierarchy

Do not make every location link to every other location without a user need.

## Step 9: Manage profiles

For each profile:

- verify ownership
- verify eligibility
- verify name
- verify address handling
- verify phone
- verify location page
- verify hours
- verify categories
- verify services
- verify attributes
- verify review link
- monitor edits
- store before and after evidence

Use location-specific website tracking.

Do not send every profile to the homepage when a strong approved location page exists and is the correct destination.

## Step 10: Manage citations

Maintain citation records per location.

Check:

- core platforms
- industry sources
- local sources
- old addresses
- old phone numbers
- duplicate records
- brand-only records
- location records

Do not merge location citations into one identity when separate eligible locations exist.

Do not create location citations for planned or ineligible locations.

## Step 11: Manage reviews

Use the correct location-specific review link.

Rules:

- send the request for the location that served the customer
- do not move reviews between profiles
- do not ask staff to review another branch
- do not copy one response across every location
- protect private information
- route serious issues to the correct location owner
- report review metrics per location before creating a brand rollup

## Step 12: Manage structured data

Use:

- one Organization entity for the brand
- one stable LocalBusiness entity per eligible location
- unique identifiers
- correct location URLs
- accurate NAP
- accurate hours
- accurate services
- accurate area served
- relationships to the brand entity

Do not place all location addresses in one LocalBusiness object.

Do not create location entities for pages that do not represent real operations.

## Step 13: Measure by location

Track per location:

- profile actions
- reviews
- Search Console page and query data
- conversions
- calls
- citations
- geogrid settings and results
- completed work
- verified outcomes

Brand rollups must state:

- locations included
- date range
- missing locations
- aggregation method
- weighted or unweighted method
- data source differences

Do not average ranks from different grid settings without explanation.

## Step 14: Handle openings, moves, and closures

### Opening

- confirm eligibility
- confirm opening date
- create location record
- prepare page
- prepare profile
- prepare citations
- keep status planned until open
- verify customer access
- publish only with approval

### Move

- preserve the location ID
- record old and new NAP
- plan profile update
- update location page
- update schema
- update citations
- plan redirects when URLs change
- monitor duplicates and old records

### Temporary closure

- use accurate temporary status
- update hours and customer messaging
- preserve the location record
- do not remove the page automatically

### Permanent closure

- confirm legal and operational closure
- record final date
- update profile
- update website
- redirect only when a useful replacement exists
- update citations
- preserve historical evidence

## Step 15: Approval and access

Define:

- central owner
- location owner
- emergency approver
- profile access
- website access
- citation access
- reporting access
- change rights
- rollback rights

A central standard does not authorize a false local fact.

## Step 16: Quality control

Before publication or live change:

- confirm the location ID
- confirm the right profile
- confirm the right page
- confirm the right phone
- confirm the right hours
- confirm the right services
- confirm local proof
- confirm no cross-location review or result
- run the Human Writing SOP
- run the publication checklist

## Completion standard

The multi-location system is complete when:

- every location has a controlled record
- eligibility is supported
- profiles and pages align
- brand and local facts are separated
- shared material is approved
- citations and reviews stay location-specific
- reporting can be reproduced
- openings, moves, and closures have workflows
- no fake or planned location is presented as active
