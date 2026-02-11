# Personal Finance Tracker

## Overview

This project is a **Personal Finance Tracker** built using **Django**, designed to help users manage income, expenses, and budgets, and gain insights into their financial activity through reports and dashboards.

The focus of the project is on **backend architecture, data modeling, and business logic**, with a minimal frontend implemented using Django Templates.

The application is **deployed and functional**, backed by a **production-grade PostgreSQL database**.

---

## Tech Stack

- **Backend:** Django, Django REST Framework  
- **Database:** PostgreSQL (production configuration)  
- **Authentication:** Django Auth + Google OAuth  
- **Frontend:** Django Templates  
- **Email:** SendGrid  
- **Deployment:** Render  

---

## Key Features

### User Authentication
- User registration and login
- Google OAuth-based authentication
- Secure session handling

### Transaction Management
- Add, edit, and delete income and expense transactions
- Each transaction includes amount, date, description, and category
- Supports negative values (refunds) and precise decimal handling
- Safe handling of category deletions with existing transactions

### Dashboard
- Overview of total income, expenses, and savings
- Monthly summaries
- Visual representation of financial data

### Reporting
- Monthly income vs expense reports
- Category-wise expense summaries
- Backend-driven aggregation logic

### Budgeting
- Budget limits per expense category
- Real-time tracking of spent vs allocated amount
- Budget utilization visible in the dashboard

### Email Notifications
- Backend logic implemented for budget threshold notifications
- Integrated with **SendGrid** for email delivery
- **Note:** While the notification workflow is implemented and functional at the backend level, email delivery via SendGrid is currently not working reliably in the deployed environment due to external service configuration issues

---

## Architecture Highlights

- PostgreSQL used as the primary relational database with proper schema design
- Clean separation between models, views, and business logic
- Financial data stored using decimal-safe fields
- User-level data isolation enforced at the database query level
- Designed to be extensible for future analytics and integrations

---

## Deployment & Setup

link:
https://finance-tracker-0oc7.onrender.com

The application is deployed with environment variables used for sensitive configuration.

### Environment Variables
```env
SECRET_KEY=...
DEBUG=False
DATABASE_URL=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
SENDGRID_API_KEY=...
EMAIL_FROM=...
