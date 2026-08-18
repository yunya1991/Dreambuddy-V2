"""Integration tests for V15Executor adapter layer."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from dreamos.capabilities.trading.v15_executor import V15Executor, V15ExecutorNode
from dreamos.shared.state import State, NodeStatus


class TestV15ExecutorAdapter:
    """Test V15Executor as 14-V15 adapter layer."""

    def test_executor_initialization_with_coin_pool(self):
        """Test that V15Executor loads coin pool on initialization."""
        executor = V15Executor(dry_run=True)
        
        # Should load coin pool from coin_pool.json
        assert "long_pool" in executor._coin_pool
        assert "short_pool" in executor._coin_pool
        assert isinstance(executor._coin_pool["long_pool"], list)
        assert isinstance(executor._coin_pool["short_pool"], list)

    def test_executor_rejects_hold_signal(self):
        """Test that HOLD signal is rejected."""
        executor = V15Executor(dry_run=True)
        signal = {
            "symbol": "BTC",
            "direction": "HOLD",
            "confidence": 0.75,
            "entry_price": 50000.0,
        }
        result = executor.execute_signal(signal)
        
        assert result["status"] == "REJECTED"
        assert result["reason"] == "HOLD signal not executable"
        assert result["source"] == "14-V15-adapter"

    def test_executor_rejects_long_only_gate(self):
        """Test that long_only gate rejects SHORT signals."""
        executor = V15Executor(dry_run=True, long_only=True)
        signal = {
            "symbol": "BTC",
            "direction": "SHORT",
            "confidence": 0.75,
            "entry_price": 50000.0,
        }
        result = executor.execute_signal(signal)
        
        assert result["status"] == "REJECTED"
        assert result["reason"] == "v15_long_only"
        assert result["source"] == "14-V15-adapter"

    def test_executor_rejects_symbol_not_in_pool(self):
        """Test that symbol not in coin pool is rejected."""
        executor = V15Executor(dry_run=True)
        
        # Mock coin pool to only include BTC
        executor._coin_pool = {
            "long_pool": [{"symbol": "BTC", "score": 0.8}],
            "short_pool": [],
        }
        
        signal = {
            "symbol": "ETH",  # Not in pool
            "direction": "LONG",
            "confidence": 0.75,
            "entry_price": 3000.0,
        }
        result = executor.execute_signal(signal)
        
        assert result["status"] == "REJECTED"
        assert "not in long_pool" in result["reason"]
        assert result["source"] == "14-V15-adapter"

    @patch('dreamos.capabilities.trading.v15_executor.v15_trader')
    def test_executor_delegates_to_14v15(self, mock_v15_trader):
        """Test that V15Executor delegates to 14-V15 execute_open_position."""
        # Mock 14-V15 functions
        mock_v15_trader.load_state.return_value = {"positions": {}}
        mock_v15_trader._get_okx_client.return_value = Mock()
        mock_v15_trader.execute_open_position.return_value = True
        mock_v15_trader.save_state.return_value = None
        
        executor = V15Executor(dry_run=True)
        
        # Mock coin pool to include BTC
        executor._coin_pool = {
            "long_pool": [{"symbol": "BTC", "score": 0.8}],
            "short_pool": [],
        }
        
        signal = {
            "symbol": "BTC",
            "direction": "LONG",
            "confidence": 0.75,
            "entry_price": 50000.0,
        }
        result = executor.execute_signal(signal)
        
        # Should delegate to 14-V15
        assert mock_v15_trader.execute_open_position.called
        assert result["source"] == "14-V15-adapter"
        assert result["status"] in ["OPEN", "REJECTED", "ERROR"]

    def test_executor_initializes_hyperliquid_client(self):
        """Test that HyperliquidClient is initialized when dry_run=False."""
        import dreamos.capabilities.trading.v15_executor as v15_module
        
        # Save original state
        original_hl_available = v15_module._HL_AVAILABLE
        original_hl_client = getattr(v15_module, 'HyperliquidClient', None)
        
        try:
            # Create mock HyperliquidClient class
            mock_hl_client_instance = Mock()
            mock_hl_client_class = Mock(return_value=mock_hl_client_instance)
            
            # Patch module attributes
            v15_module._HL_AVAILABLE = True
            v15_module.HyperliquidClient = mock_hl_client_class
            
            executor = V15Executor(dry_run=False, agent_id="c")
            
            # Should initialize HyperliquidClient
            assert mock_hl_client_class.called
            assert mock_hl_client_class.call_args[0][0] == "c"
            assert executor._hl_client is not None
            assert executor._hl_adapter is not None
        finally:
            # Restore original state
            v15_module._HL_AVAILABLE = original_hl_available
            if original_hl_client is not None:
                v15_module.HyperliquidClient = original_hl_client


class TestV15ExecutorNode:
    """Test V15ExecutorNode DreamOS wrapper."""

    def test_node_returns_valid_noderesult(self):
        """Test that V15ExecutorNode returns valid NodeResult."""
        node = V15ExecutorNode()
        state = State(market={
            "symbol": "BTC",
            "direction": "LONG",
            "confidence": 0.75,
            "entry_price": 50000.0,
        })
        result = node.execute_core(state)
        
        assert result.node_id == "V15_EXECUTOR"
        assert result.status in [NodeStatus.SUCCESS, NodeStatus.DEGRADED]
        assert 0.0 <= result.confidence <= 1.0
        assert "source" in result.outputs
        assert result.outputs["source"] == "14-V15-adapter"

    def test_node_handles_hold_signal(self):
        """Test that V15ExecutorNode handles HOLD signal correctly."""
        node = V15ExecutorNode()
        state = State(market={
            "symbol": "BTC",
            "direction": "HOLD",
            "confidence": 0.75,
            "entry_price": 50000.0,
        })
        result = node.execute_core(state)
        
        assert result.node_id == "V15_EXECUTOR"
        assert result.status == NodeStatus.DEGRADED
        assert result.outputs["status"] == "REJECTED"
        assert result.outputs["reason"] == "HOLD signal not executable"
