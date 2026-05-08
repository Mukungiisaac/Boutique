from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func
from app import db
from app.models import Goal, Product, Sale, SaleItem, ProductVariant, Category

goals_bp = Blueprint('goals', __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _period_start(period):
    now = datetime.utcnow()
    if period == 'day':
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'week':
        return now - timedelta(days=7)
    else:  # month
        return now - timedelta(days=30)


def _compute_progress(goal):
    """Return (current_value, progress_pct, label) for a goal."""
    start = _period_start(goal.period)

    if goal.goal_type == 'revenue':
        current = db.session.query(func.sum(Sale.total_amount)).filter(
            Sale.status == 'completed', Sale.created_at >= start
        ).scalar() or 0
        label = f"KES {current:,.0f} of KES {goal.target:,.0f}"

    elif goal.goal_type == 'profit':
        revenue = db.session.query(func.sum(Sale.total_amount)).filter(
            Sale.status == 'completed', Sale.created_at >= start
        ).scalar() or 0
        cost = db.session.query(func.sum(SaleItem.quantity * SaleItem.cost_price)).join(Sale).filter(
            Sale.status == 'completed', Sale.created_at >= start
        ).scalar() or 0
        current = revenue - cost
        label = f"KES {current:,.0f} of KES {goal.target:,.0f}"

    elif goal.goal_type == 'transactions':
        current = Sale.query.filter(
            Sale.status == 'completed', Sale.created_at >= start
        ).count()
        label = f"{int(current)} of {int(goal.target)} sales"

    elif goal.goal_type == 'stock':
        if goal.product_id:
            current = db.session.query(func.sum(ProductVariant.stock_qty)).filter(
                ProductVariant.product_id == goal.product_id
            ).scalar() or 0
            label = f"{int(current)} of {int(goal.target)} units"
        else:
            current = db.session.query(func.sum(ProductVariant.stock_qty)).scalar() or 0
            label = f"{int(current)} of {int(goal.target)} total units"
    else:
        current = 0
        label = "—"

    pct = min(int((current / goal.target) * 100), 100) if goal.target > 0 else 0
    return round(float(current), 2), pct, label


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@goals_bp.route('/goals')
@login_required
def index():
    goals = Goal.query.filter_by(user_id=current_user.id, is_active=True)\
        .order_by(Goal.created_at.desc()).all()
    products = Product.query.filter_by(is_active=True).order_by(Product.name).all()

    goals_data = []
    for g in goals:
        current, pct, label = _compute_progress(g)
        goals_data.append({
            'goal':    g,
            'current': current,
            'pct':     pct,
            'label':   label,
        })

    return render_template('goals/index.html',
                           goals_data=goals_data,
                           products=products)


@goals_bp.route('/goals/add', methods=['POST'])
@login_required
def add_goal():
    data = request.get_json() or {}
    title      = data.get('title', '').strip()
    goal_type  = data.get('goal_type', '')
    period     = data.get('period', '')
    target     = data.get('target')
    product_id = data.get('product_id') or None

    if not title:
        return jsonify({'success': False, 'message': 'Title is required.'}), 400
    if goal_type not in ('revenue', 'profit', 'transactions', 'stock'):
        return jsonify({'success': False, 'message': 'Invalid goal type.'}), 400
    if period not in ('day', 'week', 'month'):
        return jsonify({'success': False, 'message': 'Invalid period.'}), 400
    try:
        target = float(target)
        if target <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Target must be a positive number.'}), 400

    goal = Goal(
        user_id=current_user.id,
        title=title,
        goal_type=goal_type,
        period=period,
        target=target,
        product_id=int(product_id) if product_id else None,
    )
    db.session.add(goal)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Goal created!', 'id': goal.id})


@goals_bp.route('/goals/delete/<int:goal_id>', methods=['POST'])
@login_required
def delete_goal(goal_id):
    goal = Goal.query.filter_by(id=goal_id, user_id=current_user.id).first_or_404()
    goal.is_active = False
    db.session.commit()
    return jsonify({'success': True})


@goals_bp.route('/goals/progress')
@login_required
def progress():
    """JSON endpoint — returns live progress for all active goals (used by dashboard)."""
    goals = Goal.query.filter_by(user_id=current_user.id, is_active=True).all()
    result = []
    for g in goals:
        current, pct, label = _compute_progress(g)
        result.append({
            'id':        g.id,
            'title':     g.title,
            'goal_type': g.goal_type,
            'period':    g.period,
            'target':    g.target,
            'current':   current,
            'pct':       pct,
            'label':     label,
            'done':      pct >= 100,
        })
    return jsonify(result)
