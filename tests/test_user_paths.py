import os
import unittest
from unittest.mock import patch, MagicMock
from lufus.user_paths import get_best_starting_dir, ENV_DOWNLOAD_DIR


class TestUserPaths(unittest.TestCase):
    def setUp(self):
        # Clear the var before each test
        if ENV_DOWNLOAD_DIR in os.environ:
            del os.environ[ENV_DOWNLOAD_DIR]

    def test_get_best_starting_dir_with_env(self):
        """Test that it prioritizes the environment variable if it points to a valid dir."""
        test_path = "/tmp/lufus_test_dir"
        os.makedirs(test_path, exist_ok=True)
        try:
            os.environ[ENV_DOWNLOAD_DIR] = test_path
            self.assertEqual(get_best_starting_dir(), test_path)
        finally:
            if os.path.exists(test_path):
                os.rmdir(test_path)

    @patch("lufus.user_paths.user_downloads_dir")
    @patch("os.path.isdir")
    def test_get_best_starting_dir_with_xdg(self, mock_isdir, mock_downloads):
        """Test that it uses XDG_DOWNLOAD_DIR if env is not set"""
        mock_downloads.return_value = "/home/user/Downloads"
        mock_isdir.side_effect = lambda p: p == "/home/user/Downloads"

        self.assertEqual(get_best_starting_dir(), "/home/user/Downloads")

    @patch("lufus.user_paths.user_downloads_dir")
    @patch("os.path.isdir")
    def test_get_best_starting_dir_with_custom_name(self, mock_isdir, mock_downloads):
        """Test that it handles edge cases/translated names (like ~/Potato or ~/Téléchargements) (~/Potato is a great Downloads folder name btw)"""
        custom_path = "/home/user/Téléchargements"
        mock_downloads.return_value = custom_path
        mock_isdir.side_effect = lambda p: p == custom_path

        self.assertEqual(get_best_starting_dir(), custom_path)

    @patch("lufus.user_paths.user_downloads_dir")
    @patch("pathlib.Path.home")
    @patch("os.path.isdir")
    def test_get_best_starting_dir_fallback_to_home(self, mock_isdir, mock_home, mock_downloads):
        """Test fallback to Home if Downloads is not found."""
        mock_downloads.return_value = "/home/user/Downloads"
        mock_home.return_value = MagicMock()
        mock_home.return_value.__str__.return_value = "/home/user"

        # Downloads does not exist
        mock_isdir.return_value = False

        self.assertEqual(get_best_starting_dir(), "/home/user")


if __name__ == "__main__":
    unittest.main()
